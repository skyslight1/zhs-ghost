#!/usr/bin/env python3
"""回归检查：windowed exe 的 stdout/stderr 代理不能和 loguru 互相递归。

成功时打印 `STREAM_PROXY_OK` 并返回 0；如果又出现无限递归，进程会抛
RecursionError（或者直接卡死），由调用方按超时处理。

为什么单独放一个文件：这个 bug 只有真正执行 `setup_logging()` 之后才会
触发，纯 import 检查发现不了。必须起一个干净的解释器实跑。

    python tests/check_stream_proxy.py
"""
from __future__ import annotations

import os
import sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)


def main() -> int:
    from zhsgo.gui.window import _StreamProxy
    from zhsgo.logger import get, setup

    tmp = os.path.join(os.environ.get("TEMP", "."), "zhsgo-stream-proxy-check")
    real_out, real_err = sys.stdout, sys.stderr

    try:
        # 复刻 windowed exe 的状态
        sys.stdout = _StreamProxy(os.path.join(tmp, "stdout.log"))
        sys.stderr = _StreamProxy(os.path.join(tmp, "stderr.log"))

        # App.__init__ 会做这件事：把 sys.stderr 注册成一个 loguru sink
        setup(tmp, "INFO", to_console=True)

        # 真正会触发递归的调用
        log = get()
        for i in range(200):
            log.info(f"probe {i}")
        log.warning("probe warning")
        log.error("probe error")

        # 顺带验证 print 也不会炸（CLI 分支里的 selfcheck 大量用 print）
        print("print goes to proxy")
        sys.stderr.write("stderr goes to proxy\n")
        sys.stdout.flush()
        sys.stderr.flush()
    finally:
        sys.stdout, sys.stderr = real_out, real_err

    print("STREAM_PROXY_OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
