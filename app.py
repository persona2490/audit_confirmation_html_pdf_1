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

def call_deepseek_ai(account_data, risk_data):
    client = OpenAI(
        api_key=st.secrets["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com"
    )

    prompt = f"""
你是一名审计经理，请根据以下银行账户信息和规则检查结果，生成审计风险分析。

【账户信息】
{account_data}

【规则检查结果】
{risk_data}

请输出：
1. 总体风险等级
2. 主要风险点
3. 审计关注事项
4. 处理建议

要求：
- 面向审计人员
- 不要编造不存在的信息
- 语言简洁
- 如果信息完整，也要说明仍需人工复核
"""

    response = client.chat.completions.create(
        model="deepseek-chat",
        messages=[
            {"role": "system", "content": "你是一名严谨的审计经理，擅长银行函证风险分析。"},
            {"role": "user", "content": prompt}
        ],
        temperature=0.2
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

st.subheader("账户AI审计建议")

account_data = df.head(20).to_json(orient="records", force_ascii=False)

risk_data = "当前仅完成基础字段校验，未发现明显缺失字段。"

if st.button("生成AI审计建议"):
    with st.spinner("DeepSeek 正在分析账户信息..."):
        ai_advice = call_deepseek_ai(account_data, risk_data)
        st.markdown(ai_advice)

st.subheader("第三步：预览询证函")

preview_index = st.selectbox(
    "选择要预览的账户",
    range(len(df)),
    format_func=lambda i: f"{df.iloc[i]['账户名称']} - {df.iloc[i]['开户行']}"
)

preview_row = df.iloc[preview_index]

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