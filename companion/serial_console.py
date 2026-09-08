#!/usr/bin/env python3
"""串口控制台诊断：读 ESP32-C3 USB 串口输出，判断应用固件是否在运行。

用法：
    python serial_console.py            # 自动挑第一个 cu.usbmodem*，读 12s
    python serial_console.py /dev/cu.usbmodem101 20

判读：
  · 看到 FoloToy / boot / BLE / wifi 之类日志 → 应用固件在跑（问题在 BLE 广播触发）
  · 完全无输出、或只有乱码 → 固件没跑 / 卡在下载模式 / 波特率不对
"""
import glob
import sys
import time

import serial


def pick_port(arg: str | None) -> str:
    if arg:
        return arg
    cands = sorted(glob.glob("/dev/cu.usbmodem*") + glob.glob("/dev/cu.usbserial*"))
    if not cands:
        print("[serial] 没找到 cu.usbmodem* 设备。")
        print("         → 确认 USB 数据线已插、设备开机；充电-only 线不出现串口。")
        sys.exit(1)
    if len(cands) > 1:
        print(f"[serial] 发现多个串口 {cands}，默认用 {cands[0]}")
    return cands[0]


def main():
    port = pick_port(sys.argv[1] if len(sys.argv) > 1 else None)
    secs = float(sys.argv[2]) if len(sys.argv) > 2 else 12.0

    print(f"[serial] 打开 {port} @115200，监听 {secs:g}s …")
    print("[serial] 提示：期间可试着按一下设备上的 Reset 键，会看到重启日志\n" + "-" * 60)
    try:
        ser = serial.Serial(port, 115200, timeout=0.5)
    except Exception as e:
        print(f"[serial] 打开失败: {e!r}")
        print("         → 串口可能被浏览器标签页(esptool/刷机页)占用，请先关掉那些标签页。")
        sys.exit(1)

    buf = b""
    t0 = time.time()
    try:
        while time.time() - t0 < secs:
            chunk = ser.read(512)
            if chunk:
                buf += chunk
                try:
                    print(chunk.decode("utf-8", "replace"), end="", flush=True)
                except Exception:
                    print(repr(chunk))
    except KeyboardInterrupt:
        pass
    finally:
        ser.close()

    print("\n" + "-" * 60)
    if not buf.strip():
        print("[结果] 串口毫无输出。")
        print("       → 可能：① 卡在 esptool 下载模式(关浏览器标签+拔插USB) ② 固件为空 ③ 波特率不符")
        print("       → 下一步：关掉所有刷机/TRAÉ 网页标签 → 拔插 USB → 重跑本脚本")
    else:
        print(f"[结果] 收到 {len(buf)} 字节。请把它发给我判断（尤其含 FoloToy/BLE/wifi/error 的行）。")


if __name__ == "__main__":
    main()
