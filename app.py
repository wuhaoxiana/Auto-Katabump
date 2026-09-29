#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import time
import subprocess
import requests
from seleniumbase import SB

# ============================================================
# 多账号配置（读取 GitHub Actions Secrets）
#   KATABUMP_EMAIL    : 每行一个邮箱
#   KATABUMP_PASSWORD : 每行一个密码（与邮箱按行对应）
# TG 通知与代理 (NODE_LINK) 同样走 Secrets（敏感信息）
# ============================================================

TG_CHAT_ID   = os.environ.get("TG_CHAT_ID") or ""        # tg通知 chat id(可选)
TG_BOT_TOKEN = os.environ.get("TG_BOT_TOKEN") or ""      # tg通知bot token(可选)

BASE_URL = "https://dashboard.katabump.com"  # 网站链接


def _split_lines(raw: str):
    """把多行 / 逗号 / 分号分隔的配置拆成列表，自动去空行和首尾空格。"""
    if not raw:
        return []
    text = raw.replace("\r\n", "\n").replace("\r", "\n")
    for sep in (",", ";", "|"):
        if "\n" not in text and sep in text:
            text = text.replace(sep, "\n")
    return [line.strip() for line in text.split("\n") if line.strip()]


def _parse_selected(raw: str, total: int):
    """解析手动触发填写的账号序号（如 1,3 或 2-4），返回 0 起始的下标列表。

    序号非法或超出范围时抛 ValueError，避免误跑全部账号。
    """
    text = raw.replace("，", ",").replace("、", ",").replace("－", "-").replace(" ", "")
    if not text:
        return None  # 留空 = 全部

    picked = set()
    for part in text.split(","):
        if not part:
            continue
        if "-" in part:
            a, _, b = part.partition("-")
            if not (a.isdigit() and b.isdigit()):
                raise ValueError(f"区间格式不正确: {part}")
            lo, hi = int(a), int(b)
            if lo > hi:
                lo, hi = hi, lo
            picked.update(range(lo, hi + 1))
        elif part.isdigit():
            picked.add(int(part))
        else:
            raise ValueError(f"序号格式不正确: {part}")

    if 0 in picked:
        raise ValueError("账号序号从 1 开始")
    out_of_range = [p for p in sorted(picked) if p > total]
    if out_of_range:
        raise ValueError(f"序号超出范围: {out_of_range}（当前共 {total} 个账号）")
    return [p - 1 for p in sorted(picked)]


def load_accounts():
    """从 Secrets 载入多账号列表，返回 [(email, password), ...]。"""
    emails = _split_lines(os.environ.get("KATABUMP_EMAIL", ""))
    passwords = _split_lines(os.environ.get("KATABUMP_PASSWORD", ""))

    if not emails or not passwords:
        print("❌ 未配置 KATABUMP_EMAIL / KATABUMP_PASSWORD（Secrets，每行一个）")
        return []

    if len(emails) != len(passwords):
        print(
            f"❌ 账号数量不匹配：邮箱 {len(emails)} 个，密码 {len(passwords)} 个。"
            "请确保 KATABUMP_EMAIL 与 KATABUMP_PASSWORD 每行一一对应。"
        )
        return []

    accounts = list(zip(emails, passwords))

    # 手动触发时按序号筛选（renew.yml 传入，留空 = 全部）
    selected_raw = (os.environ.get("SELECTED_ACCOUNTS") or "").strip()
    if selected_raw:
        try:
            idx_list = _parse_selected(selected_raw, len(accounts))
        except ValueError as e:
            print(f"❌ 账号序号解析失败: {e}")
            return []
        if idx_list is not None:
            accounts = [accounts[i] for i in idx_list]
            preview = ", ".join(mask_email(e) for e, _ in accounts)
            print(f"🎯 手动选择账号 [{selected_raw}]: {preview}")

    print(f"👥 已载入 {len(accounts)} 个账号")
    return accounts


def mask_email(email: str) -> str:
    """邮箱脱敏：保留用户名前2位和后2位，中间用 **** 代替。"""
    if "@" in email:
        name, domain = email.split("@", 1)
        if len(name) > 4:
            return f"{name[:2]}****{name[-2:]}@{domain}"
        return f"{name}@{domain}"
    return email[:2] + "****"


#  Telegram 汇总推送模块
def send_tg_summary(results):
    """所有账号跑完后，把每个账号的结果汇成一条 TG 通知发送。"""
    if not TG_BOT_TOKEN or not TG_CHAT_ID:
        print("ℹ️ 未配置 TG_BOT_TOKEN 或 TG_CHAT_ID，跳过 Telegram 推送。")
        return
    if not results:
        return

    # 获取北京时间 (UTC+8)
    local_time = time.gmtime(time.time() + 8 * 3600)
    current_time_str = time.strftime("%Y-%m-%d", local_time)

    ok = sum(1 for r in results if r["ok"])
    total = len(results)

    sep = "—" * 10
    lines = [
        "🇫🇷 KataBump 多账号续期汇总",
        sep,
        f"📊 成功 {ok} / 共 {total}",
        f"🕒 完成时间: {current_time_str}",
        sep,
    ]
    for r in results:
        lines.append(f"{r['icon']} {r['status']}")
        lines.append(f"👤 续期账户: {mask_email(r['email'])}")
        lines.append(f"📄 页面提示: {(r.get('alert') or '无')[:150]}")
        lines.append(sep)

    url = f"https://api.telegram.org/bot{TG_BOT_TOKEN}/sendMessage"
    try:
        requests.post(
            url,
            json={"chat_id": TG_CHAT_ID, "text": "\n".join(lines)},
            timeout=10,
        )
        print("📩 Telegram 汇总通知发送成功！")
    except Exception as e:
        print(f"⚠️ Telegram 汇总通知发送异常: {e}")


#  页面注入脚本
_EXPAND_JS = """
(function() {
    var ts = document.querySelector('input[name="cf-turnstile-response"]');
    if (!ts) return 'no-turnstile';
    var el = ts;
    for (var i = 0; i < 20; i++) {
        el = el.parentElement;
        if (!el) break;
        var s = window.getComputedStyle(el);
        if (s.overflow === 'hidden' || s.overflowX === 'hidden' || s.overflowY === 'hidden')
            el.style.overflow = 'visible';
        el.style.minWidth = 'max-content';
    }
    document.querySelectorAll('iframe').forEach(function(f){
        if (f.src && f.src.includes('challenges.cloudflare.com')) {
            f.style.width = '300px'; f.style.height = '65px';
            f.style.minWidth = '300px';
            f.style.visibility = 'visible'; f.style.opacity = '1';
        }
    });
    return 'done';
})()
"""

_EXISTS_JS = """
(function(){
    return document.querySelector('input[name="cf-turnstile-response"]') !== null;
})()
"""

_SOLVED_JS = """
(function(){
    var i = document.querySelector('input[name="cf-turnstile-response"]');
    return !!(i && i.value && i.value.length > 20);
})()
"""

_WININFO_JS = """
(function(){
    return {
        sx: window.screenX || 0,
        sy: window.screenY || 0,
        oh: window.outerHeight,
        ih: window.innerHeight
    };
})()
"""

# ===== 自动续期相关 =====

# 在模态框内查找 iframe 并展开，返回点击坐标
_ALTCHA_EXPAND_JS = """
(function() {
    var modal = document.querySelector('div.modal.show') || document;
    var iframes = modal.querySelectorAll('iframe');
    for (var i = 0; i < iframes.length; i++) {
        var r = iframes[i].getBoundingClientRect();
        if (r.width > 0 && r.height > 0) {
            iframes[i].style.width  = '300px';
            iframes[i].style.height = '150px';
            iframes[i].style.minWidth  = '300px';
            iframes[i].style.minHeight = '150px';
            iframes[i].style.visibility = 'visible';
            iframes[i].style.opacity = '1';
            var el = iframes[i];
            for (var j = 0; j < 10; j++) {
                el = el.parentElement;
                if (!el) break;
                el.style.overflow = 'visible';
            }
            var r2 = iframes[i].getBoundingClientRect();
            return { cx: Math.round(r2.x + 30), cy: Math.round(r2.y + r2.height / 2) };
        }
    }
    return null;
})()
"""

# 检测 ALTCHA 是否已验证通过
_ALTCHA_SOLVED_JS = """
(function(){
    var modal = document.querySelector('div.modal.show') || document;
    // hidden input 有值
    var inputs = modal.querySelectorAll('input[type="hidden"]');
    for (var i = 0; i < inputs.length; i++) {
        var n = (inputs[i].name || '').toLowerCase();
        if ((n.includes('altcha') || n.includes('captcha')) &&
            inputs[i].value && inputs[i].value.length > 20) return true;
    }
    // checkbox 变为 disabled
    var cbs = modal.querySelectorAll('input[type="checkbox"]');
    for (var j = 0; j < cbs.length; j++) {
        if (cbs[j].disabled) return true;
    }
    // widget data-state 属性
    var w = modal.querySelector('[data-state="verified"],.altcha--verified,.altcha-verified');
    if (w) return true;
    return false;
})()
"""


#  底层输入工具
def js_fill_input(sb, selector: str, text: str):
    safe_text = text.replace('\\', '\\\\').replace('"', '\\"')
    sb.execute_script(f"""
    (function(){{
        var el = document.querySelector('{selector}');
        if (!el) return;
        var nativeInputValueSetter = Object.getOwnPropertyDescriptor(window.HTMLInputElement.prototype, "value").set;
        if (nativeInputValueSetter) {{
            nativeInputValueSetter.call(el, "{safe_text}");
        }} else {{
            el.value = "{safe_text}";
        }}
        el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        el.dispatchEvent(new Event('change', {{ bubbles: true }}));
    }})()
    """)


def _activate_window():
    for cls in ["chrome", "chromium", "Chromium", "Chrome", "google-chrome"]:
        try:
            r = subprocess.run(["xdotool", "search", "--onlyvisible", "--class", cls], capture_output=True, text=True, timeout=3)
            wids = [w for w in r.stdout.strip().split("\n") if w.strip()]
            if wids:
                subprocess.run(["xdotool", "windowactivate", "--sync", wids[0]], timeout=3, stderr=subprocess.DEVNULL)
                time.sleep(0.2)
                return
        except Exception:
            pass
    try:
        subprocess.run(["xdotool", "getactivewindow", "windowactivate"], timeout=3, stderr=subprocess.DEVNULL)
    except Exception:
        pass


#  人机验证处理（使用 SeleniumBase 内置 uc_gui_click_captcha）
def handle_turnstile(sb) -> bool:
    print("🔍 处理 Cloudflare Turnstile 验证...")
    time.sleep(2)

    # 检查是否已静默通过
    if sb.execute_script(_SOLVED_JS):
        print("✅ 已静默通过")
        return True

    # 尝试展开 Turnstile（防止被父容器 overflow:hidden 裁剪）
    for _ in range(3):
        try: sb.execute_script(_EXPAND_JS)
        except Exception: pass
        time.sleep(0.5)

    # 使用 SeleniumBase 内置 uc_gui_click_captcha 处理 Turnstile
    # 该方法自动完成：检测验证码类型 → 定位 iframe → 计算坐标 → PyAutoGUI 平滑点击
    for attempt in range(6):
        if sb.execute_script(_SOLVED_JS):
            print(f"✅ Turnstile 通过（第 {attempt} 次尝试）")
            return True

        print(f"🖱️ 第 {attempt + 1} 次调用 uc_gui_click_captcha...")
        try:
            sb.uc_gui_click_captcha()
        except Exception as e:
            print(f"⚠️ uc_gui_click_captcha 调用异常: {e}")

        # 等待验证结果（最多 8 秒）
        for _ in range(16):
            time.sleep(0.5)
            if sb.execute_script(_SOLVED_JS):
                print(f"✅ Turnstile 通过（第 {attempt + 1} 次尝试）")
                return True

        print(f"⚠️ 第 {attempt + 1} 次未通过，重试...")

    print("  ❌ Turnstile 6 次均失败")
    return False


#  账户登录（多账号：email / password 由外部传入）
def login(sb, email: str, password: str) -> bool:
    print(f"🌐 打开登录页面: {BASE_URL}/auth/login")
    sb.uc_open_with_reconnect(BASE_URL + "/auth/login", reconnect_time=8)
    time.sleep(8)

    # 先等待 Cloudflare 验证通过（最多等 30 秒）
    print("⏳ 等待 Cloudflare 验证通过...")
    cf_passed = False
    for i in range(30):
        page_src = sb.get_page_source() or ""
        if 'input[name="email"]' in page_src.lower() or 'name="email"' in page_src.lower():
            cf_passed = True
            print(f"✅ Cloudflare 验证已通过（{i+1}s）")
            break
        time.sleep(1)
    if not cf_passed:
        print("⚠️ Cloudflare 验证可能未通过，继续尝试...")

    try:
        sb.wait_for_element('input[type="email"]', timeout=15)
    except Exception:
        # 尝试大写选择器作为后备
        try:
            sb.wait_for_element('input[type="Email"]', timeout=5)
        except Exception:
            print("❌ 页面未加载出登录表单")
            cur_url = sb.get_current_url()
            page_title = sb.get_title() or ""
            print(f"  当前 URL: {cur_url}")
            print(f"  当前标题: {page_title}")
            sb.save_screenshot(f"login_load_fail_{mask_email(email).replace('@', '_at_')}.png")
            return False

    print("🍪 关闭可能的 Cookie 弹窗...")
    try:
        for btn in sb.find_elements("button"):
            if "Accept" in (btn.text or ""):
                btn.click()
                time.sleep(0.5)
                break
    except Exception:
        pass

    print(f"📧 填写邮箱: {mask_email(email)}")
    js_fill_input(sb, 'input[type="email"]', email)
    time.sleep(1)

    print("🔑 填写密码...")
    js_fill_input(sb, 'input[type="password"]', password)
    time.sleep(3)

    # 等待 Turnstile 验证框出现（最多 10 秒）
    print("⏳ 等待 Turnstile 验证框出现...")
    ts_found = False
    for i in range(10):
        if sb.execute_script(_EXISTS_JS):
            ts_found = True
            print(f"✅ 检测到 Turnstile（{i+1}s）")
            break
        time.sleep(1)

    if ts_found:
        if not handle_turnstile(sb):
            print("❌ 登录界面的 Turnstile 验证失败")
            sb.save_screenshot(f"login_turnstile_fail_{mask_email(email).replace('@', '_at_')}.png")
            return False
    else:
        print("ℹ️ 未检测到 Turnstile")

    print("🖱️ 敲击回车提交表单...")
    sb.press_keys('input[name="password"]', '\n')

    print("⏳ 等待登录跳转...")
    for _ in range(12):
        time.sleep(1)
        cur_url = sb.get_current_url().split('?')[0].lower()
        page_title = sb.get_title() or ""
        if cur_url.startswith(f"{BASE_URL}/dashboard") or "Dashboard | KataBump" in page_title.lower():
            break

    cur_url = sb.get_current_url().split('?')[0].lower()
    page_title = sb.get_title() or ""
    if cur_url.startswith(f"{BASE_URL}/dashboard") or "Dashboard | KataBump" in page_title.lower():
        print(f"✅ 登录成功！(URL: {sb.get_current_url()}, Title: {page_title})")
        return True

    print(f"❌ 登录失败，页面未跳转到账户页。(URL: {sb.get_current_url()}, Title: {page_title})")
    sb.save_screenshot(f"login_failed_{mask_email(email).replace('@', '_at_')}.png")
    return False


def logout(sb):
    """退出当前账号，清理 cookie / storage，为下一个账号做准备。"""
    print("🚪 退出当前账号并清理会话...")
    try:
        sb.uc_open_with_reconnect(BASE_URL + "/auth/logout", reconnect_time=4)
        time.sleep(3)
    except Exception:
        pass
    try:
        sb.delete_all_cookies()
    except Exception:
        pass
    try:
        sb.execute_script(
            "try { window.localStorage.clear(); window.sessionStorage.clear(); } catch(e) {}"
        )
    except Exception:
        pass
    time.sleep(1)


# ===== 自动续期流程 =====

def _read_alert(sb):
    """读取页面第一个 Bootstrap alert 的文本，找不到返回空串"""
    try:
        el = sb.find_element("div.alert", timeout=4)
        return (el.text or "").strip()
    except Exception:
        return ""


def _goto_server_detail(sb, email: str, result: dict) -> bool:
    """在 Dashboard 首页查找并点击 See 进入服务器详情页"""
    print("\n🖥️  正在进入服务器续期页...")
    time.sleep(5)

    # 检查页面顶部是否已有"还无法续期"全局提示
    alert_text = _read_alert(sb)
    if alert_text and "can't renew" in alert_text.lower():
        print(f"ℹ️  页面顶部提示: {alert_text}")
        result.update(ok=False, icon="ℹ️", status="未到续期时间", alert=alert_text)
        return False

    # 多种选择器尝试查找 See 链接
    selectors = [
        'a[href*="/servers/edit?id="]',
        'td a[href*="/servers/edit"]',
        'table a[href*="/servers/edit"]',
        'table td a',
    ]

    see_link = None
    for sel in selectors:
        try:
            see_link = sb.find_element(sel, timeout=8)
            print(f"✅ 通过选择器找到链接: {sel}")
            break
        except Exception:
            continue

    # 选择器全部失败，尝试通过文本内容查找
    if see_link is None:
        print("⚠️ 选择器未命中，尝试文本匹配...")
        try:
            for a in sb.find_elements("a"):
                if (a.text or "").strip().lower() == "see":
                    see_link = a
                    print("✅ 通过文本 'See' 找到链接")
                    break
        except Exception:
            pass

    if see_link is None:
        # 打印调试信息帮助排查
        cur_url = sb.get_current_url()
        title = sb.get_title() or ""
        print(f"❌ 未找到 'See' 链接")
        print(f"当前 URL: {cur_url}")
        print(f"页面标题: {title}")
        try:
            links = sb.find_elements("a")
            print(f"     页面共 {len(links)} 个链接:")
            for a in links[:20]:
                href = a.get_attribute("href") or ""
                txt  = (a.text or "").strip()[:30]
                if href:
                    print(f"       - [{txt}] -> {href}")
        except Exception:
            pass
        sb.save_screenshot(f"servers_page_fail_{mask_email(email).replace('@', '_at_')}.png")
        result.update(ok=False, icon="❌", status="未找到服务器入口")
        return False

    print("🖱️  点击 'See' 进入服务器详情页...")
    see_link.click()
    time.sleep(5)
    print(f"📄 当前页面: {sb.get_current_url()}")
    return True


def _open_renew_modal(sb) -> bool:
    """滚动到 Renew 按钮并点击，打开模态框"""
    print("\n🔄 查找 Renew 按钮...")
    try:
        renew_btn = sb.find_element('button[data-bs-target="#renew-modal"]', timeout=10)
    except Exception:
        try:
            renew_btn = sb.find_element('button.btn.btn-outline-primary', timeout=5)
        except Exception:
            print("  ❌ 未找到 Renew 按钮")
            return False

    sb.execute_script("""
        (function(){
            var btn = document.querySelector('button[data-bs-target="#renew-modal"]')
                     || document.querySelector('button.btn.btn-outline-primary');
            if (btn) btn.scrollIntoView({behavior:'smooth',block:'center'});
        })()
    """)
    time.sleep(0.8)
    renew_btn.click()
    print("🖱️ 已点击 Renew 按钮，等待确认框...")
    time.sleep(3)

    try:
        sb.find_element('div.modal.show', timeout=5)
        print("✅ Renew 模态框已弹出")
        return True
    except Exception:
        print("⚠️ 模态框未弹出")
        return False


def _submit_renew(sb):
    """点击模态框内的 Renew 提交按钮"""
    print("🖱️  点击模态框中的 Renew 按钮...")
    try:
        submit = sb.find_element('div.modal-footer button.btn.btn-primary', timeout=10)
        submit.click()
    except Exception:
        sb.execute_script("""
            (function(){
                var m = document.querySelector('button.btn.btn-primary');
                if (!m) return;
                var bs = m.querySelectorAll('button');
                for (var i = 0; i < bs.length; i++)
                    if (/renew/i.test(bs[i].textContent)) bs[i].click();
            })()
        """)
    time.sleep(8)


def _check_renew_result(sb, email: str, result: dict):
    """读取页面 alert 提示，判断续期结果并记录（最后统一汇总推送）"""
    print("\n📋 检查续期结果...")
    alert_text = _read_alert(sb)
    if not alert_text:
        time.sleep(3)
        alert_text = _read_alert(sb)

    if alert_text:
        print(f"📩 页面提示: {alert_text}")
        low = alert_text.lower()
        if "can't renew" in low or "unable" in low:
            result.update(ok=False, icon="⏳", status="未到续期时间", alert=alert_text)
        elif any(kw in low for kw in ("renewed", "success", "extended")):
            result.update(ok=True, icon="✅", status="续期成功", alert=alert_text)
        else:
            result.update(ok=True, icon="ℹ️", status="续期操作已执行", alert=alert_text)
    else:
        print("ℹ️ 未检测到明确的提示框，可能续期操作未生效")
        result.update(ok=True, icon="ℹ️", status="续期操作已执行", alert="未检测到明确提示")


def renew_server(sb, email: str, result: dict):
    """登录成功后调用：自动进入详情页 -> Renew -> 提交"""
    print("\n" + "#" * 25)
    print("  开始自动续期流程")
    print("#" * 25)

    if not _goto_server_detail(sb, email, result):
        return

    if not _open_renew_modal(sb):
        result.update(ok=False, icon="❌", status="Renew 按钮/模态框异常")
        return

    _submit_renew(sb)
    _check_renew_result(sb, email, result)


def process_account(sb, email: str, password: str, index: int, total: int) -> dict:
    """处理单个账号：登录 -> 续期 -> 退出，返回结果字典。"""
    print("\n" + "=" * 46)
    print(f"  账号 [{index}/{total}] {mask_email(email)}")
    print("=" * 46)

    result = {"email": email, "ok": False, "icon": "❌", "status": "未执行", "alert": "无"}

    try:
        if login(sb, email, password):
            renew_server(sb, email, result)
        else:
            print("\n❌ 登录失败，跳过该账号的续期操作。")
            result.update(ok=False, icon="❌", status="登录失败", alert="无")
    except Exception as e:
        print(f"❌ 账号处理异常: {e}")
        result.update(ok=False, icon="❌", status="处理异常", alert=str(e)[:200])
    finally:
        try:
            logout(sb)
        except Exception:
            pass

    return result


#  脚本执行入口 (可选代理)
def main():
    print("#" * 25)
    print("   katabump 多账号自动登录续期")
    print("#" * 25)

    accounts = load_accounts()
    if not accounts:
        print("❌ 无可用账号，脚本退出。")
        return 1

    IS_PROXY = os.environ.get("IS_PROXY", "false").lower() == "true"
    proxy_str = os.environ.get("PROXY_SERVER", "").strip() or "http://127.0.0.1:1081"
    sb_kwargs = {"uc": True, "headless": False}

    if IS_PROXY:
        print(f"🔗 挂载代理: {proxy_str}")
        sb_kwargs["proxy"] = proxy_str
    else:
        print("🌐 未使用代理，直连访问")

    print("🚀 启动浏览器...")
    results = []
    total = len(accounts)

    with SB(**sb_kwargs) as sb:
        try:
            sb.open("https://api.ip.sb/ip")
            print(f"📍  当前出口IP: {sb.get_text('body')}")
        except Exception:
            pass

        for idx, (email, password) in enumerate(accounts, 1):
            results.append(process_account(sb, email, password, idx, total))
            if idx < total:
                print("\n⏳ 等待 8 秒后处理下一个账号...")
                time.sleep(8)

    # 汇总输出
    print("\n" + "#" * 46)
    print("  全部账号处理完毕，结果汇总")
    print("#" * 46)
    ok = sum(1 for r in results if r["ok"])
    for idx, r in enumerate(results, 1):
        print(f"  {idx}. {r['icon']} {mask_email(r['email'])} — {r['status']}")
    print(f"\n📊 成功 {ok} / 共 {total}")

    send_tg_summary(results)

    # 全部失败时以非零码退出，方便 Actions 标红
    return 0 if ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
