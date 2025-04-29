#!/usr/bin/env python
from mininet.net import Mininet
from mininet.topo import Topo
from mininet.link import TCLink
from mininet.util import quietRun
from time import sleep, time
import matplotlib.pyplot as plt
import pandas as pd
import numpy as np
import os

class SingleSwitchTopo(Topo):
    def build(self):
        h1 = self.addHost('h1')
        h2 = self.addHost('h2')
        h3 = self.addHost('h3')
        s1 = self.addSwitch('s1')
        self.addLink(h1, s1)
        self.addLink(h2, s1)
        self.addLink(h3, s1, cls=TCLink, bw=100, delay='50ms', max_queue_size=2000)

def main():
    # 清理残留进程
    os.system('sudo mn -c 2>/dev/null')
    os.system('sudo pkill -f "ss -tin" 2>/dev/null')
    os.system('sudo rm -f /tmp/cwnd.log 2>/dev/null')

    # 创建拓扑
    topo = SingleSwitchTopo()
    net = Mininet(topo=topo, link=TCLink)
    try:
        net.start()
        print("[DEBUG] 拓扑已启动")

        # 配置交换机流表
        s1 = net.get('s1')
        quietRun('ovs-ofctl add-flow s1 actions=normal')
        print(f"[DEBUG] 交换机流表配置完成:\n{s1.cmd('ovs-ofctl dump-flows s1')}")

        # 启动 iperf3 服务端（h3）
        h3 = net.get('h3')
        h3.cmd('killall iperf3 2> /dev/null')
        h3.cmd('iperf3 -s &')
        print("[DEBUG] iperf3服务端已启动")

        # 启动 cwnd 监控（h1）
        h1 = net.get('h1')
        cwnd_log = '/tmp/cwnd.log'
        monitor_cmd = (
            "while true; do "
            "timestamp=$(date +%%s.%%3N) && "  # 强制时间戳获取成功
            # 获取 cwnd，失败时返回 NaN
            "cwnd=$(/usr/bin/ss -tin state established dst 10.0.0.3 | grep -oP 'cwnd:\\K\\d+' || echo 'NaN') && "
            # 关键修复：使用双引号包裹变量，确保输出完整行
            "echo \"$timestamp,$cwnd\" || exit 1; "  # 任意步骤失败则终止
            "sleep 0.1; "
            "done > %s &" % cwnd_log
        )
        h1.cmd(monitor_cmd)
        print("[DEBUG] cwnd监控已启动")
        sleep(1)  # 确保监控进程启动

        # 启动 iperf3 客户端（h1 → h3）
        print("[DEBUG] 启动iperf3客户端...")
        start_time = time()
        iperf_output = h1.cmd('iperf3 -c 10.0.0.3 -t 10 -C cubic')
        end_time = start_time + 10  # 实验总时长10秒
        print(f"[DEBUG] iperf3客户端输出:\n{iperf_output}")

        # 终止监控进程
        h1.cmd("pkill -f 'ss -tin'")
        net.stop()

        # 处理数据并打印日志内容
        if os.path.exists(cwnd_log) and os.path.getsize(cwnd_log) > 0:
            # 打印完整日志内容
            print("\n[DEBUG] /tmp/cwnd.log 完整内容:")
            with open(cwnd_log, 'r') as f:
                for line_num, line in enumerate(f, 1):
                    print(f"Line {line_num}: {line.strip()}")

            # 读取日志并解析时间戳和cwnd
            df = pd.read_csv(
                cwnd_log,
                names=['timestamp', 'cwnd'],
                dtype={'timestamp': float, 'cwnd': str},  # 临时读取为字符串
                on_bad_lines='skip'
            )
            # 转换cwnd列为数值，空值或无效字符串转为NaN
            df['cwnd'] = pd.to_numeric(df['cwnd'], errors='coerce')
            # 过滤实验时间段外的数据
            df = df[(df['timestamp'] >= start_time) & (df['timestamp'] <= end_time)]
            # 删除无效值（cwnd=NaN或10）
            df = df.dropna(subset=['cwnd'])
            # df = df[df['cwnd'] != 10]

            if not df.empty:
                # 生成相对时间轴（从0开始）
                df['time'] = df['timestamp'] - start_time
                # 按时间排序
                df = df.sort_values('time')
                # 打印前10条数据样本
                print("\n[DEBUG] 处理后数据样本:")
                print(df.head(10))

                # 绘图
                plt.figure(figsize=(12,6))
                plt.plot(df['time'].to_numpy(), df['cwnd'].to_numpy(), label='TCP Cubic', color='blue')
                plt.xlabel('Time (s)')
                plt.ylabel('Congestion Window (packets)')
                plt.title('TCP Cubic cwnd Dynamics')
                plt.legend()
                plt.grid(True)
                plt.savefig('cwnd_curve.png')
                plt.show()
            else:
                print("[ERROR] 有效数据为空！")
        else:
            print("[ERROR] 无有效数据生成！")
    except Exception as e:
        print(f"[ERROR] 发生异常: {e}")
    finally:
        os.system('sudo mn -c 2>/dev/null')

if __name__ == '__main__':
    main()
