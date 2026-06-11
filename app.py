import io
import os
import zipfile
from datetime import date

import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from jinja2 import Environment, FileSystemLoader, select_autoescape
from openai import OpenAI
from playwright.sync_api import sync_playwright


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


def inject_css():
    st.markdown(
        """
        <style>
        .block-container {
            padding-top: 2rem;
            padding-bottom: 3rem;
            max-width: 1100px;
        }

        .hero {
            padding: 34px 36px;
            border-radius: 22px;
            background: linear-gradient(135deg, #0f172a 0%, #1d4ed8 55%, #2563eb 100%);
            color: white;
            margin-bottom: 26px;
            box-shadow: 0 18px 40px rgba(37, 99, 235, 0.25);
        }

        .hero h1 {
            font-size: 38px;
            margin-bottom: 8px;
            font-weight: 800;
        }

        .hero p {
            font-size: 17px;
            opacity: 0.9;
            margin-bottom: 0;
        }

        .section-card {
            background: #ffffff;
            padding: 24px 26px;
            border-radius: 18px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 8px 24px rgba(15, 23, 42, 0.06);
            margin-bottom: 22px;
        }

        .section-title {
            font-size: 22px;
            font-weight: 800;
            color: #0f172a;
            margin-bottom: 12px;
        }

        .section-desc {
            color: #64748b;
            font-size: 14px;
            margin-bottom: 18px;
        }

        .small-label {
            color: #64748b;
            font-size: 13px;
            margin-bottom: 4px;
        }

        .info-box {
            padding: 16px;
            border-radius: 14px;
            background: #f8fafc;
            border: 1px solid #e2e8f0;
            margin-bottom: 10px;
        }

        .ai-box {
            padding: 20px;
            border-radius: 16px;
            background: #f8fafc;
            border-left: 5px solid #2563eb;
            border-top: 1px solid #e2e8f0;
            border-right: 1px solid #e2e8f0;
            border-bottom: 1px solid #e2e8f0;
        }

        .success-pill {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 999px;
            background: #dcfce7;
            color: #166534;
            font-weight: 700;
            font-size: 13px;
        }

        .warning-pill {
            display: inline-block;
            padding: 6px 12px;
            border-radius: 999px;
            background: #fef3c7;
            color: #92400e;
            font-weight: 700;
            font-size: 13px;
        }

        div[data-testid="stMetric"] {
            background: white;
            padding: 18px;
            border-radius: 16px;
            border: 1px solid #e5e7eb;
            box-shadow: 0 6px 20px rgba(15, 23, 42, 0.05);
        }

        .stButton > button {
            border-radius: 12px;
            font-weight: 700;
            height: 44px;
        }

        .stDownloadButton > button {
            border-radius: 12px;
            font-weight: 700;
            height: 44px;
        }

        iframe {
            border-radius: 14px;
            border: 1px solid #e5e7eb;
            background: white;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def clean_value(value):
    if pd.isna(value):
        return ""
    return str(value).strip()


def parse_balance(value):
    try:
        return float(str(value).replace(",", "").strip())
    except Exception:
        return 0.0


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


def render_html(context):
    env = Environment(
        loader=FileSystemLoader("templates"),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("confirmation.html")
    return template.render(**context)


def render_pdf(context):
    html = render_html(context)

    with sync_playwright() as p:
        launch_options = {"args": ["--no-sandbox"]}

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
    text = str(text)
    for ch in bad_chars:
        text = text.replace(ch, "_")
    return text[:80]


def call_deepseek_ai(account_info):
    client = OpenAI(
        api_key=st.secrets["DEEPSEEK_API_KEY"],
        base_url="https://api.deepseek.com",
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
6. 不要输出思考过程。

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
            {"role": "user", "content": prompt},
        ],
        temperature=0.1,
    )

    return response.choices[0].message.content


def build_context(row, number, firm_name, contact, phone, email, audit_year, reply_address, postcode, confirmation_date, note):
    return {
        "编号": number,
        "银行名称": clean_value(row["开户行"]),
        "账户名称": clean_value(row["账户名称"]),
        "银行账号": clean_value(row["银行账号"]),
        "账户类型": clean_value(row["账户类型"]),
        "币种": clean_value(row["币种"]),
        "账户余额": f'{parse_balance(row["余额"]):,.2f}',
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


st.set_page_config(
    page_title="智能银行询证函生成平台",
    page_icon="🏦",
    layout="centered",
)

inject_css()

with st.sidebar:
    st.markdown("## 🏦 智能函证平台")
    st.caption("AI辅助审计 · 自动函证 · PDF导出")
    st.divider()
    st.markdown("### 功能流程")
    st.markdown("✅ 1. 填写经办人信息")
    st.markdown("✅ 2. 上传账户Excel")
    st.markdown("✅ 3. 选择账户预览")
    st.markdown("✅ 4. AI审计建议")
    st.markdown("✅ 5. 批量生成PDF")
    st.divider()
    st.info("建议先上传少量测试数据，确认格式后再批量生成。")

st.markdown(
    """
    <div class="hero">
        <h1>🏦 智能银行询证函生成平台</h1>
        <p>AI辅助审计 · 自动风险分析 · 一键生成银行询证函PDF</p>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Step 1 · 填写函证经办人信息</div>', unsafe_allow_html=True)
st.markdown('<div class="section-desc">用于自动填充银行询证函中的事务所、联系人和回函信息。</div>', unsafe_allow_html=True)

with st.form("user_info_form"):
    col1, col2 = st.columns(2)
    with col1:
        firm_name = st.text_input("会计师事务所", value="210会计师事务所")
        contact = st.text_input("联系人", value="刘鳗瞩")
        phone = st.text_input("电话", value="12345678910")
        email = st.text_input("邮箱", value="123456789")
    with col2:
        audit_year = st.text_input("审计年度", value="2026年")
        reply_address = st.text_input("回函地址", value="")
        postcode = st.text_input("邮编", value="")
        confirmation_date = st.date_input("函证截止日期", value=date.today())

    note = st.text_area("补充说明", value="无")
    submitted = st.form_submit_button("保存经办人信息", use_container_width=True)

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

st.markdown('<span class="success-pill">经办人信息已填写完整</span>', unsafe_allow_html=True)
st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Step 2 · 上传银行账户表</div>', unsafe_allow_html=True)
st.markdown('<div class="section-desc">Excel需包含：账户名称、银行账号、开户行、币种、账户类型、余额。</div>', unsafe_allow_html=True)

uploaded_file = st.file_uploader("上传Excel文件", type=["xlsx", "xls"])

if uploaded_file is None:
    st.info("请上传账户表后继续。")
    st.stop()

df = pd.read_excel(uploaded_file)

valid, message = validate_excel(df)
if not valid:
    st.error(message)
    st.stop()

st.success(f"Excel校验通过，共读取 {len(df)} 条账户记录。")

balance_total = df["余额"].apply(parse_balance).sum()
bank_count = df["开户行"].nunique()
company_count = df["账户名称"].nunique()

m1, m2, m3 = st.columns(3)
m1.metric("账户数量", len(df))
m2.metric("开户行数量", bank_count)
m3.metric("余额合计", f"{balance_total / 10000:,.2f} 万")

with st.expander("查看账户表前10行", expanded=True):
    st.dataframe(df.head(10), width="stretch")

st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Step 3 · 选择账户并生成AI审计建议</div>', unsafe_allow_html=True)
st.markdown('<div class="section-desc">选择一个账户后，系统会根据账户类型和审计规则生成AI风险分析。</div>', unsafe_allow_html=True)

preview_index = st.selectbox(
    "选择要预览和分析的账户",
    range(len(df)),
    format_func=lambda i: f"{df.iloc[i]['账户名称']} - {df.iloc[i]['开户行']} - {df.iloc[i]['账户类型']}",
)

preview_row = df.iloc[preview_index]

account_info = f"""
账户名称：{clean_value(preview_row["账户名称"])}
开户行：{clean_value(preview_row["开户行"])}
账户类型：{clean_value(preview_row["账户类型"])}
币种：{clean_value(preview_row["币种"])}
余额：{clean_value(preview_row["余额"])}
"""

col_left, col_right = st.columns([1, 1.35])

with col_left:
    st.markdown("#### 当前账户信息")
    st.markdown(
        f"""
        <div class="info-box">
            <div class="small-label">账户名称</div>
            <b>{clean_value(preview_row["账户名称"])}</b>
        </div>
        <div class="info-box">
            <div class="small-label">开户行</div>
            <b>{clean_value(preview_row["开户行"])}</b>
        </div>
        <div class="info-box">
            <div class="small-label">账户类型</div>
            <b>{clean_value(preview_row["账户类型"])}</b>
        </div>
        <div class="info-box">
            <div class="small-label">币种 / 余额</div>
            <b>{clean_value(preview_row["币种"])} · {parse_balance(preview_row["余额"]):,.2f}</b>
        </div>
        """,
        unsafe_allow_html=True,
    )

with col_right:
    st.markdown("#### AI审计建议")
    if st.button("🤖 生成AI审计建议", use_container_width=True):
        with st.spinner("DeepSeek 正在结合审计规则分析账户信息..."):
            try:
                ai_advice = call_deepseek_ai(account_info)
                st.markdown('<div class="ai-box">', unsafe_allow_html=True)
                st.markdown(ai_advice)
                st.markdown("</div>", unsafe_allow_html=True)
            except Exception as e:
                st.error(f"AI分析失败：{e}")
    else:
        st.markdown(
            """
            <div class="ai-box">
            点击上方按钮后，系统将根据账户类型、币种和余额生成审计风险提示。
            </div>
            """,
            unsafe_allow_html=True,
        )

st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Step 4 · 银行询证函预览</div>', unsafe_allow_html=True)
st.markdown('<div class="section-desc">以下为当前选中账户生成的银行询证函预览。</div>', unsafe_allow_html=True)

preview_context = build_context(
    row=preview_row,
    number=f"{audit_year.replace('年', '')}-{preview_index + 1:03d}",
    firm_name=firm_name,
    contact=contact,
    phone=phone,
    email=email,
    audit_year=audit_year,
    reply_address=reply_address,
    postcode=postcode,
    confirmation_date=confirmation_date,
    note=note,
)

preview_html = render_html(preview_context)

components.html(
    preview_html,
    height=850,
    scrolling=True,
)

st.markdown("</div>", unsafe_allow_html=True)

st.markdown('<div class="section-card">', unsafe_allow_html=True)
st.markdown('<div class="section-title">Step 5 · 批量生成银行询证函PDF</div>', unsafe_allow_html=True)
st.markdown('<div class="section-desc">系统将为Excel中的每一行账户生成一份PDF，并打包为ZIP下载。</div>', unsafe_allow_html=True)

if st.button("📦 生成银行询证函ZIP", use_container_width=True):
    zip_buffer = io.BytesIO()

    with st.spinner("正在生成PDF，请稍候..."):
        with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zip_file:
            for i, row in df.iterrows():
                number = f"{audit_year.replace('年', '')}-{i + 1:03d}"

                context = build_context(
                    row=row,
                    number=number,
                    firm_name=firm_name,
                    contact=contact,
                    phone=phone,
                    email=email,
                    audit_year=audit_year,
                    reply_address=reply_address,
                    postcode=postcode,
                    confirmation_date=confirmation_date,
                    note=note,
                )

                pdf_bytes = render_pdf(context)
                filename = f"{number}_{safe_filename(context['账户名称'])}_{safe_filename(context['银行名称'])}.pdf"
                zip_file.writestr(filename, pdf_bytes)

    zip_buffer.seek(0)

    st.success("银行询证函已全部生成。")
    st.download_button(
        label="⬇️ 下载银行询证函ZIP",
        data=zip_buffer,
        file_name="银行询证函.zip",
        mime="application/zip",
        use_container_width=True,
    )

st.markdown("</div>", unsafe_allow_html=True)