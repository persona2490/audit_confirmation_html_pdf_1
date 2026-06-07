# 智能银行询证函生成助手

## 功能

输入 Excel 账户表，填写经办人信息，自动批量生成银行询证函 PDF，并打包为 ZIP 下载。

## Excel 必须包含字段

- 账户名称
- 银行账号
- 开户行
- 币种
- 账户类型
- 余额

## 安装依赖

```bash
pip install -r requirements.txt
```

## 运行

```bash
streamlit run app.py
```

## 默认经办人信息

- 会计师事务所：210会计师事务所
- 联系人：刘鳗瞩
- 电话：12345678910
- 邮箱：123456789
- 审计年度：2026年

## 说明

本版本采用：

Excel → Python → HTML模板(Jinja2) → PDF

核心模板文件在：

```text
templates/confirmation.html
```

后续如果要调整询证函格式，主要修改这个 HTML 文件即可。