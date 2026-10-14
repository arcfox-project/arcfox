"""mitmproxy addon：只记录 ARCFOX 车控鉴权/账号相关请求，输出到 stdout 与 /tmp/arcfox_capture.log"""
from mitmproxy import http

KEY_HOSTS = ("bjev", "arcfox", "easemob", "huanxin")
KEY_PATHS = ("/auth/", "/login", "/signin", "/signinsms", "/refreshtoken", "/vcam/")


def _hit(url: str) -> bool:
    low = url.lower()
    return any(h in low for h in KEY_HOSTS) or any(p in low for p in KEY_PATHS)


def request(flow: http.HTTPFlow) -> None:
    if not _hit(flow.request.pretty_url):
        return
    line = f"REQ {flow.request.method} {flow.request.pretty_url}\n"
    for k, v in flow.request.headers.items():
        line += f"  H {k}: {v}\n"
    if flow.request.content:
        line += f"  BODY: {flow.request.get_text(strict=False)}\n"
    print(line, flush=True)
    with open("/tmp/arcfox_capture.log", "a") as f:
        f.write(line)


def response(flow: http.HTTPFlow) -> None:
    if not _hit(flow.request.pretty_url):
        return
    line = f"RES {flow.response.status_code} {flow.request.pretty_url}\n"
    if flow.response and flow.response.content:
        line += f"  BODY: {flow.response.get_text(strict=False)[:2000]}\n"
    print(line, flush=True)
    with open("/tmp/arcfox_capture.log", "a") as f:
        f.write(line)
