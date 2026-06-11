import io
import zipfile
from datetime import date

import pandas as pd
import streamlit as st
from jinja2 import Environment, FileSystemLoader, select_autoescape
# from weasyprint import HTML
from playwright.sync_api import sync_playwright
import streamlit.components.v1 as components
import os
from openai import OpenAI

REQUIRED_COLUMNS = ["账户名称", "银行账号", "开户行", "币种", "账户类型", "余额"]

AUDIT_RULES = """
【保证金户】
风险等级：高
关注点：资金是否受限；是否对应真实合同、保函或承兑汇票；是否存在担保责任或潜在负债。
审计程序：获取保证金协议；检查保函、承兑汇票或相关合同；核实资金受限性质；检查财务报表披露。

【监管户】
风险等级：高
关注点：是否属于受限资金；是否存在违规支取；资金用途是否符合监管协议。
审计程序：获取监管协议；执行银行函证；检查资金支取记录；核实资金用途。

【资本金户】
风险等级：高
关注点：资金来源是否合法；外汇登记是否完整；资金用途是否合规。
审计程序：检查投资协议、验资报告、外汇登记资料；执行银行函证；检查资金流向。

【外币户】
风险等级：中
关注点：汇率折算是否正确；汇兑损益是否确认；是否存在异常跨境交易。
审计程序：检查期末汇率；复核外币折算；检查跨境流水。

【定期存款】
风险等级：中高
关注点：是否存在质押、冻结或受限；利息收入是否准确。
审计程序：获取存单；检查质押协议；复核利息收入。

【募集资金户】
风险等级：高
关注点：是否专款专用；资金用途是否合规；是否存在挪用。
审计程序：检查募集资金专项报告；核对资金用途；检查审批文件。

【贷款专户】
风险等级：高
关注点：借款合同是否完整；利息计提是否准确；资金用途是否符合约定。
审计程序：检查借款合同；检查贷款流水；复核利息。

【基本户】
风险等级：低
关注点：账户是否真实存在；余额是否与账面一致；是否存在未披露账户。
审计程序：银行函证；对账单检查；资金流水抽查。

【一般户】
风险等级：中
关注点：是否长期未使用；是否存在体外资金循环；是否纳入财务核算。
审计程序：银行函证；核查账户用途；检查资金流水。
"""

def html_to_pdf(html_content, output_path):
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.set_content(html_content, wait_until="networkidle")
        page.pdf(
            path=output_path,
            format="A4",
            print_background=True,
            margin={
                "top": "15mm",
                "right": "15mm",
                "bottom": "15mm",
                "left": "15mm",
            },
        )
        browser.close()

def clean_value(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def validate_excel(df):
    missing_cols = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing_cols:
        return False, f"Excel缺少字段：{', '.join(missing_cols)}"

    empty_rows = []
    for idx, row in df.iterrows():
        missing_fields = [c for c in REQUIRED_COLUMNS if clean_value(row[c]) == ""]
        if missing_fields:
            empty_rows.append(f"第{idx + 2}行缺少：{', '.join(missing_fields)}")

    if empty_rows:
        return False, "\n".join(empty_rows[:20])

    return True, "校验通过"


# def render_pdf(context):
#     env = Environment(
#         loader=FileSystemLoader("templates"),
#         autoescape=select_autoescape(["html"])
#     )
#     template = env.get_template("confirmation.html")
#     html = template.render(**context)

#     pdf_bytes = HTML(string=html, base_url=".").write_pdf()
#     return pdf_bytes

def render_html(context):
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"])
    )
    template = env.get_template("confirmation.html")
    html = template.render(**context)
    return html

def render_pdf(context):
    html = render_html(context)

    with sync_playwright() as p:
        launch_options = {
            "args": ["--no-sandbox"]
        }

        if os.path.exists("/usr/bin/chromium"):
            launch_options["executable_path"] = "/usr/bin/chromium"

        browser = p.chromium.launch(**launch_options)
        page = browser.new_page()
        page.set_content(html, wait_until="networkidle")
        pdf_bytes = page.pdf(
            format="A4",
            print_background=True,
            margin={
                "top": "15mm",
                "right": "15mm",
                "bottom": "15mm",
                "left": "15mm",
            },
        )
        browser.close()

    return pdf_bytes

def safe_filename(text):
    bad_chars = ['\\', '/', ':', '*', '?', '"', '<', '>', '|']
    for ch in bad_chars:
        text = text.replace(ch, "_")
    return text[:80]

def call_deepseek_ai(account_info):
    client = OpenAI(
        api_key=st.secrets["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com"
    )

    prompt = f"""
你是一名银行函证审计专家。

请根据以下审计规则库和账户信息，生成审计风险分析。

【审计规则库】
{AUDIT_RULES}

【账户信息】
{account_info}

要求：
1. 先识别账户类型。
2. 只分析与账户类型最匹配的规则。
3. 不要把所有规则都总结一遍。
4. 如果账户类型没有匹配规则，输出“知识库中无对应规则”。
5. 语言面向审计人员，简洁专业。

输出格式：

## 风险等级

## 风险分析

## 需要关注的问题

## 建议执行的审计程序
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一名严谨的银行函证审计专家。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.1
    )

    return response.choices[0].message.content

st.set_page_config(page_title="智能银行询证函生成助手", layout="centered")

st.title("智能银行询证函生成助手")
st.caption("Excel → HTML模板 → PDF")

st.subheader("第一步：填写函证经办人信息")

with st.form("user_info_form"):
    firm_name = st.text_input("会计师事务所", value="210会计师事务所")
    contact = st.text_input("联系人", value="刘鳗瞩")
    phone = st.text_input("电话", value="12345678910")
    email = st.text_input("邮箱", value="123456789")
    audit_year = st.text_input("审计年度", value="2026年")
    reply_address = st.text_input("回函地址", value="")
    postcode = st.text_input("邮编", value="")
    confirmation_date = st.date_input("函证截止日期", value=date.today())
    note = st.text_area("补充说明", value="无")

    submitted = st.form_submit_button("保存经办人信息")

required_info = {
    "会计师事务所": firm_name,
    "联系人": contact,
    "电话": phone,
    "邮箱": email,
    "审计年度": audit_year,
}

info_ok = all(str(v).strip() for v in required_info.values())

if not info_ok:
    st.warning("请先填写完整经办人信息，填写完成后才能上传账户表。")
    st.stop()

st.success("经办人信息已填写完整。")

st.subheader("第二步：上传账户表")

uploaded_file = st.file_uploader("上传Excel文件", type=["xlsx", "xls"])

if uploaded_file is None:
    st.info("请上传包含账户名称、银行账号、开户行、币种、账户类型、余额的Excel。")
    st.stop()

df = pd.read_excel(uploaded_file)

valid, message = validate_excel(df)
if not valid:
    st.error(message)
    st.stop()

st.success(f"Excel校验通过，共读取 {len(df)} 条账户记录。")
st.dataframe(df.head(10), use_container_width=True)


st.subheader("第三步：预览询证函")

preview_index = st.selectbox(
    "选择要预览的账户",
    range(len(df)),
    format_func=lambda i: f"{df.iloc[i]['账户名称']} - {df.iloc[i]['开户行']}"
)

preview_row = df.iloc[preview_index]

st.subheader("第四步：AI审计建议")

account_info = f"""
账户名称：{clean_value(preview_row["账户名称"])}
开户行：{clean_value(preview_row["开户行"])}
账户类型：{clean_value(preview_row["账户类型"])}
币种：{clean_value(preview_row["币种"])}
余额：{clean_value(preview_row["余额"])}
"""

if st.button("生成AI审计建议"):
    with st.spinner("DeepSeek 正在结合审计规则分析账户信息..."):
        ai_advice = call_deepseek_ai(account_info)
        st.markdown(ai_advice)

preview_context = {
    "编号": f"{audit_year.replace('年', '')}-{preview_index + 1:03d}",
    "银行名称": clean_value(preview_row["开户行"]),
    "账户名称": clean_value(preview_row["账户名称"]),
    "银行账号": clean_value(preview_row["银行账号"]),
    "账户类型": clean_value(preview_row["账户类型"]),
    "币种": clean_value(preview_row["币种"]),
    "账户余额": f'{float(str(preview_row["余额"]).replace(",", "")):,.2f}',
    "会计师事务所": firm_name,
    "联系人": contact,
    "电话": phone,
    "邮箱": email,
    "审计年度": audit_year,
    "回函地址": reply_address,
    "邮编": postcode,
    "函证截止日期": confirmation_date.strftime("%Y年%m月%d日"),
    "补充说明": note,
}

preview_html = render_html(preview_context)

components.html(
    preview_html,
    height=1100,
    scrolling=True
)

if st.button("生成银行询证函PDF"):
    zip_buffer = io.BytesIO()

    with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
        for i, row in df.iterrows():
            number = f"{audit_year.replace('年', '')}-{i + 1:03d}"

            context = {
                "编号": number,
                "银行名称": clean_value(row["开户行"]),
                "账户名称": clean_value(row["账户名称"]),
                "银行账号": clean_value(row["银行账号"]),
                "账户类型": clean_value(row["账户类型"]),
                "币种": clean_value(row["币种"]),
                "账户余额": f'{float(str(row["余额"]).replace(",", "")):,.2f}',
                "会计师事务所": firm_name,
                "联系人": contact,
                "电话": phone,
                "邮箱": email,
                "审计年度": audit_year,
                "回函地址": reply_address,
                "邮编": postcode,
                "函证截止日期": confirmation_date.strftime("%Y年%m月%d日"),
                "补充说明": note,
            }

            pdf_bytes = render_pdf(context)

            filename = f"{number}_{safe_filename(context['账户名称'])}_{safe_filename(context['银行名称'])}.pdf"
            zip_file.writestr(filename, pdf_bytes)

    zip_buffer.seek(0)

    st.success("生成完成。")
    st.download_button(
        label="下载银行询证函ZIP",
        data=zip_buffer,
        file_name="银行询证函.zip",
        mime="application/zip"
    )