# ui/styles.py

_CSS = """
<style>
:root {
  --bg-color: #0a0e17;
  --secondary-bg: #0d1421;
  --text-color: #e2e8f0;
  --border-color: #1a2e4a;
  --button-hover: #1b4f72;
  --header-gradient: linear-gradient(135deg, #0f1f35, #1b4f72);
  --sidebar-btn-bg: #0f1f35;
  --chat-input-bg: #0a0e17;
  --input-field-bg: #0a0e17;
  --muted-text: #94a3b8;
  --header-text: #ffffff;
  --trace-step-bg: #122947;
  --trace-meta-color: #7db8ff;
  --trace-title-color: #f5f9ff;
  --trace-sub-color: #b9d4f2;
}

@media (prefers-color-scheme: light) {
  :root {
    --bg-color: #f8fafc;
    --secondary-bg: #ffffff;
    --text-color: #1e293b;
    --border-color: #e2e8f0;
    --button-hover: #3b82f6;
    --header-gradient: linear-gradient(135deg, #2563eb, #1d4ed8);
    --sidebar-btn-bg: #f1f5f9;
    --chat-input-bg: #f8fafc;
    --input-field-bg: #ffffff;
    --muted-text: #64748b;
    --header-text: #ffffff;
    --trace-step-bg: #f1f5f9;
    --trace-meta-color: #2563eb;
    --trace-title-color: #1e293b;
    --trace-sub-color: #475569;
  }
}

.stApp,[data-testid="stAppViewContainer"]{background: var(--bg-color)!important}
.stApp *{color: var(--text-color)!important}

[data-testid="stSidebar"]{background: var(--secondary-bg)!important; border-right:1px solid var(--border-color)}
[data-testid="stSidebar"] .stButton>button{
  background: var(--sidebar-btn-bg)!important; color: var(--text-color)!important; border:1px solid var(--border-color)!important;
  border-radius:8px!important; width:100%!important; margin-bottom:5px!important;
  padding:9px 14px!important; font-size:12px!important; text-align:left!important}
[data-testid="stSidebar"] .stButton>button:hover{background: var(--button-hover)!important; border-color: var(--button-hover)!important}

[data-testid="stChatMessage"]{
  background: var(--secondary-bg)!important; border:1px solid var(--border-color)!important;
  border-radius:12px!important; padding:14px 18px!important; margin-bottom:10px!important}

[data-testid="stChatInput"] textarea{
  background: var(--secondary-bg)!important; color: var(--text-color)!important;
  border: 1px solid var(--border-color)!important; border-radius:10px!important}
[data-testid="stChatInput"]{background: var(--chat-input-bg)!important; border-top:1px solid var(--border-color)!important}

.header-card{
  background: var(--header-gradient);
  padding:18px 24px; border-radius:12px; margin-bottom:16px; border:1px solid var(--border-color)}
.header-card h1{margin:0; font-size:20px; color: var(--header-text)!important}
.header-card p{margin:4px 0 0; font-size:12px; color: #fff!important; opacity: 0.9}

.role-badge{display:inline-block; padding:4px 14px; border-radius:20px; font-size:11px; font-weight:700; margin-bottom:10px}

.trace-box{
  background: var(--bg-color); border:1px solid var(--border-color); border-radius:8px;
  padding:12px; margin-top:10px; font-size:12px; font-family:monospace}
.trace-summary{
  background: var(--secondary-bg);
  border:1px solid var(--border-color); border-radius:12px; padding:12px 14px; margin-bottom:12px;
}
.trace-chip{
  display:inline-block; margin-right:8px; margin-bottom:6px; padding:6px 12px;
  border-radius:999px; border:1px solid var(--border-color); background: var(--sidebar-btn-bg); color: var(--text-color);
  font-size:10px; font-weight:700;
}
.trace-step{
  border-radius:14px; border:1px solid var(--border-color); padding:14px 16px; margin:10px 0;
  background: var(--trace-step-bg);
}
.trace-step.route{ background-color: rgba(26, 53, 93, 0.4); border-color: var(--button-hover) }
.trace-step.tool{ background-color: rgba(19, 43, 74, 0.4); border-color: var(--border-color) }
.trace-step.result{ background-color: rgba(13, 59, 49, 0.4); border-color: #1e6d59 }
.trace-step.reply{ background-color: rgba(42, 34, 80, 0.4); border-color: #5940a2 }
.trace-step.error{ background-color: rgba(74, 25, 32, 0.4); border-color: #8f2f40 }

.trace-step .meta{
  color: var(--trace-meta-color); font-size:10px; font-weight:800; letter-spacing:.08em; text-transform:uppercase;
}
.trace-step .title{
  color: var(--trace-title-color); font-size:10px; font-weight:700; margin:6px 0 6px;
}
.trace-step .sub{
  color: var(--trace-sub-color); font-size:10px; margin-bottom:6px;
}

.login-box{
  background: var(--secondary-bg); border:1px solid var(--border-color); border-radius:14px;
  padding:36px; max-width:440px; margin:50px auto 0}

.stTextInput>div>div>input{
  background: var(--input-field-bg)!important; color: var(--text-color)!important;
  border:1px solid var(--border-color)!important; border-radius:8px!important}
.stTextInput label{color: var(--muted-text)!important; font-size:10px!important}

div[data-testid="stForm"] .stButton>button{
  background: var(--header-gradient)!important;
  color:#fff!important; border:none!important; border-radius:8px!important;
  width:100%!important; padding:12px!important; font-size:10px!important; font-weight:700!important}
div[data-testid="stForm"] .stButton>button:hover{background: var(--button-hover)!important}

.stExpander{background: var(--secondary-bg)!important; border:1px solid var(--border-color)!important; border-radius:8px!important}
</style>
"""
