# -*- coding: utf-8 -*-
"""SSH 命令执行辅助（paramiko），密码从环境变量 SRV_PASS 读取，不落盘"""
import os
import sys

import paramiko

HOST = "119.28.51.152"
USER = os.environ.get("SRV_USER", "ubuntu")


def run(cmd, timeout=120):
    pw = os.environ.get("SRV_PASS")
    if not pw:
        print("ERR: SRV_PASS not set")
        sys.exit(2)
    cli = paramiko.SSHClient()
    cli.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        cli.connect(HOST, username=USER, password=pw, timeout=15, banner_timeout=15)
    except Exception as e:
        print(f"CONNECT_FAIL: {type(e).__name__}: {e}")
        sys.exit(1)
    stdin, stdout, stderr = cli.exec_command(cmd, timeout=timeout)
    out = stdout.read().decode("utf-8", errors="replace")
    err = stderr.read().decode("utf-8", errors="replace")
    code = stdout.channel.recv_exit_status()
    cli.close()
    print(out)
    if err.strip():
        print("[stderr]", err[:2000])
    sys.exit(code)


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "echo ok")
