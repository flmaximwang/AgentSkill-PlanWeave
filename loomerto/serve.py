"""画布服务：`loomerto open <plan 数据文件>` —— 把一份 plan 打开成**可编辑的画布**。

纯 stdlib（`http.server`），只绑 127.0.0.1。页面上的每次改动都 POST 回这里，走 `edits`
（改动的唯一实现）→ `store.commit()` 写回数据文件并同步三个视图（PLAN.md / plan.html / plan.canvas）。

**它不是第二个真相**：写入只有一条路（`commit()`）；页面每次保存都带上自己读到的 `rev`
（= `plan.json` 的 `updated_at`），对不上就回 409 让人刷新重看，而不是把别人的改动盖掉。
harness 相关的东西一概不碰：只认调用方给的那**一个**数据文件。
"""

from __future__ import annotations

import json
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import edits, render, store
from .model import (BLOCK_STATUS, KINDS, PlanError, all_blocks, block_deps, block_effective,
                    claim_of, edge_deps, progress, task_status)

ASSET = Path(__file__).resolve().parent / "assets" / "canvas.html"


def _theme_css() -> str:
    """画布页用的**共用主题** —— 与 plan.html 注入的是同一份（见 `render.theme_css`）。"""
    return render.theme_css(ASSET)


def plan_rev(plan: dict) -> str:
    """这一份 plan 的版本号：`commit()` 每次落盘换一个 `rev`；老 plan 没这个字段就退回 `updated_at`。"""
    return str(plan.get("rev") or plan.get("updated_at") or "")


# ---------------------------------------------------------------- 一屏数据
def view_model(plan: dict) -> dict:
    """给画布用的一屏数据。

    派生一律用 `model` 的函数算好再发（派生状态、依赖、谁认领/谁在做、进度）——
    别让 JS 自己再实现一遍，那就是第二个真相。
    """
    tasks = []
    for t in plan.get("tasks", []):
        blocks = []
        for b in t.get("blocks") or []:
            runs = b.get("runs") or []
            cby, cat = claim_of(b)
            blocks.append({
                "id": b["id"], "title": b.get("title", ""), "kind": b.get("kind", ""),
                "status": block_effective(plan, b, t), "raw_status": b.get("status", ""),
                "owner": b.get("owner", ""), "claimed_by": cby, "claimed_at": cat,
                "exec": b.get("exec") or {}, "doc": b.get("doc", ""),
                "done_when": list(b.get("done_when") or []),
                "deps": block_deps(plan, t, b), "own_deps": list(b.get("deps") or []),
                "review_of": b.get("review_of", ""), "feedback": b.get("feedback", ""),
                "artifacts": list(b.get("artifacts") or []), "runs": runs[-5:],
                "rework": sum(1 for r in runs
                              if r.get("from") == "review" and r.get("to") != "done"),
            })
        tasks.append({"id": t["id"], "title": t.get("title", ""),
                      "status": task_status(plan, t), "owner": t.get("owner", ""),
                      "deps": list(t.get("deps") or []), "note": t.get("note", ""),
                      "blocks": blocks})
    edges = [[d, b["id"]] for t, b in all_blocks(plan) for d in edge_deps(plan, t, b)]
    done, tot = progress(plan)
    return {"slug": plan.get("slug", ""), "title": plan.get("title", ""),
            "goal": plan.get("goal", ""), "status": plan.get("status", ""),
            "rev": plan_rev(plan), "progress": [done, tot],
            "participants": plan.get("participants") or [], "tasks": tasks, "edges": edges,
            "block_statuses": BLOCK_STATUS, "task_statuses": edits.TASK_STATUS,
            "kinds": KINDS, "file": str(store.plan_path(""))}


# ---------------------------------------------------------------- HTTP
class _Handler(BaseHTTPRequestHandler):
    server_version = "loomerto-canvas"
    slug = ""

    def log_message(self, format, *args):     # 别把每个请求都喷到终端
        pass

    # —— 小工具
    def _send(self, code, body, ctype="application/json; charset=utf-8"):
        data = body if isinstance(body, bytes) else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path.split("?")[0] in ("/", "/index.html"):
            try:
                html = ASSET.read_text(encoding="utf-8").replace("/*__THEME__*/", _theme_css())
                self._send(200, html.encode("utf-8"), "text/html; charset=utf-8")
            except OSError as e:
                self._send(500, {"ok": False, "error": f"读不到画布资产 {ASSET}：{e}"})
            return
        if self.path.split("?")[0] == "/api/plan":
            try:
                self._send(200, {"ok": True, "view": view_model(store.load(self.slug))})
            except PlanError as e:
                self._send(400, {"ok": False, "error": str(e)})
            return
        self._send(404, {"ok": False, "error": "没有这个地址"})

    def do_POST(self):
        if not self.path.split("?")[0].startswith("/api/"):
            self._send(404, {"ok": False, "error": "没有这个地址"})
            return
        n = int(self.headers.get("Content-Length") or 0)
        try:
            payload = json.loads(self.rfile.read(n) or b"{}")
        except ValueError as e:
            self._send(400, {"ok": False, "error": f"请求体不是 JSON：{e}"})
            return
        try:
            plan = store.load(self.slug)
            rev = (payload.get("rev") or "").strip()
            if rev and rev != plan_rev(plan):
                self._send(409, {"ok": False,
                                 "error": "这份 plan 在别处被改过了 —— 先点「刷新」再改"})
                return
            msg, ref = self._apply(plan, payload)     # 只改 dict
            store.commit(self.slug, plan)             # 唯一的写入漏斗：json + 三个视图
            self._send(200, {"ok": True, "msg": msg, "ref": ref,
                             "view": view_model(store.load(self.slug))})
        except PlanError as e:
            self._send(400, {"ok": False, "error": str(e)})
        except Exception as e:                        # 一次坏请求不许把服务弄死
            self._send(500, {"ok": False, "error": f"{type(e).__name__}: {e}"})

    def _apply(self, plan, p) -> tuple:
        """执行一次改动，返回 `(msg, ref)`：`ref` 是这次动到的块的**当前** id（没动块就是空串）。

        跨泳道移动会换块 id，前端要靠它把选中态跟到新 id 上。
        """
        op = (p.get("op") or "").strip()
        who = (p.get("by") or "").strip() or "canvas"
        note = p.get("note") or ""
        if op == "edit":
            _b, changed = edits.edit_block(plan, p["ref"], title=p.get("title"), doc=p.get("doc"),
                                           done_when=p.get("done_when"), owner=p.get("owner"),
                                           kind=p.get("kind"), note=note, actor=who)
            return (f"{p['ref']} 改了 {'、'.join(changed)}" if changed else f"{p['ref']} 没有变化",
                    p["ref"])
        if op == "status":
            t, old = edits.set_status(plan, p["ref"], p["status"], by=who, note=note,
                                      owner=p.get("owner") or "",
                                      done_when=(p.get("done_when") if p.get("done_when") is not None else None),
                                      actor=who)
            return f"{t['id']} {old} → {p['status']}", t["id"]
        if op == "task":
            t = edits.add_task(plan, (p.get("title") or "").strip(), owner=p.get("owner") or "",
                               deps=p.get("deps") or [], note=note, actor=who)
            return f"新增任务 {t['id']}「{t['title']}」", ""
        if op == "block":
            _t, b = edits.add_block(plan, p["task"], title=(p.get("title") or "").strip(),
                                    kind=p.get("kind") or "impl", doc=p.get("doc") or "",
                                    done_when=p.get("done_when") or [], deps=p.get("deps") or [],
                                    owner=p.get("owner") or "",
                                    status=p.get("status") or "pending", actor=who)
            return f"新增块 {b['id']}「{b['title']}」", b["id"]
        if op == "reorder":
            _ = edits.reorder_blocks(plan, p["task"], p.get("order") or [])
            return f"{p['task']} 的块顺序已保存", p.get("ref") or ""
        if op == "move":
            b, _notes = edits.move_block(plan, p["ref"], p["task"], index=p.get("index"),
                                         note=note, actor=who)
            return (f"{p['ref']} → {b['id']}（换了泳道，id 与依赖接线已跟着改）", b["id"])
        raise PlanError(f"不认识的 op：{op!r}")


# ---------------------------------------------------------------- 入口
def run(slug: str, *, port: int = 0, host: str = "127.0.0.1", open_browser: bool = True) -> int:
    """起画布服务（默认绑 127.0.0.1、自动挑端口），阻塞到 Ctrl-C。返回退出码。"""
    _Handler.slug = slug
    try:
        httpd = ThreadingHTTPServer((host, port or 0), _Handler)
    except OSError as e:
        raise PlanError(f"起不了服务（{host}:{port or '自动'}）：{e}") from e
    url = f"http://{host}:{httpd.server_address[1]}/"
    print(f"画布  {url}")
    print(f"数据  {store.plan_path('')}")
    print("改一下就会写回这份数据文件并同步 PLAN.md / plan.html / plan.canvas；Ctrl-C 停。")
    if open_browser:
        threading.Thread(target=webbrowser.open, args=(url,), daemon=True).start()
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n已停。")
    finally:
        httpd.server_close()
    return 0
