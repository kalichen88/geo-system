# -*- coding: utf-8 -*-
"""SFTP 上传文件/目录到服务器"""
import os
import sys

import paramiko

HOST = "119.28.51.152"
USER = "ubuntu"
PW = "master@1.2.3."


def upload_dir(sftp, local, remote):
    for name in os.listdir(local):
        lp = os.path.join(local, name)
        rp = remote + "/" + name
        if os.path.isdir(lp):
            try:
                sftp.mkdir(rp)
            except IOError:
                pass
            upload_dir(sftp, lp, rp)
        else:
            sftp.put(lp, rp)
            print(f"upload {rp}")


def main():
    local_path, remote_path = sys.argv[1], sys.argv[2]
    t = paramiko.Transport((HOST, 22))
    t.connect(username=USER, password=PW)
    sftp = paramiko.SFTPClient.from_transport(t)
    if os.path.isdir(local_path):
        try:
            sftp.mkdir(remote_path)
        except IOError:
            pass
        upload_dir(sftp, local_path, remote_path)
    else:
        sftp.put(local_path, remote_path)
        print(f"upload {remote_path}")
    sftp.close()
    t.close()


if __name__ == "__main__":
    main()
