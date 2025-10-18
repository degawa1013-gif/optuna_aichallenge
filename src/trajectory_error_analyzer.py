#!/usr/bin/env python3
"""
trajectory_error_analyzer.py - ROSbag解析モジュール
ROSbag2から経路追従誤差を計算
"""

import numpy as np
import yaml
import sqlite3
import pandas as pd
from pathlib import Path
from typing import Tuple, Dict, List
import argparse
import xml.etree.ElementTree as ET


def find_latest_rosbag(base_dir: str = "output") -> Path:
    """最新のROSbagディレクトリを自動検出"""
    current_dir = Path.cwd()
    
    if current_dir.name == "aichallenge-2025":
        base_path = current_dir / base_dir
    elif "aichallenge-2025" in str(current_dir):
        while current_dir.name != "aichallenge-2025" and current_dir != current_dir.parent:
            current_dir = current_dir.parent
        base_path = current_dir / base_dir
    else:
        base_path = Path(base_dir)
    
    if not base_path.exists():
        raise FileNotFoundError(f"Output directory not found: {base_path}")
    
    rosbag_patterns = ["*/rosbag", "*/rosbag2_autoware"]
    rosbag_dirs = []
    
    for pattern in rosbag_patterns:
        rosbag_dirs.extend(base_path.glob(pattern))
    
    if not rosbag_dirs:
        raise FileNotFoundError(f"No rosbag directories found in {base_path}")
    
    latest_rosbag = max(rosbag_dirs, key=lambda p: p.parent.stat().st_mtime)
    print(f"🔍 検出したROSbag: {latest_rosbag}")
    return latest_rosbag


def find_reference_csv() -> Path:
    """reference.launch.xmlから経路CSVを自動検出"""
    current_dir = Path.cwd()
    
    if current_dir.name == "aichallenge-2025":
        search_base = current_dir
    elif "aichallenge-2025" in str(current_dir):
        while current_dir.name != "aichallenge-2025" and current_dir != current_dir.parent:
            current_dir = current_dir.parent
        search_base = current_dir
    else:
        search_base = Path.cwd()
    
    # reference.launch.xmlから経路ファイルパスを読み取る
    launch_xml_path = search_base / "aichallenge/workspace/src/aichallenge_submit/aichallenge_submit_launch/launch/reference.launch.xml"
    
    if launch_xml_path.exists():
        try:
            tree = ET.parse(launch_xml_path)
            root = tree.getroot()
            
            for node in root.findall(".//node[@pkg='simple_trajectory_generator']"):
                for param in node.findall(".//param[@name='csv_path']"):
                    csv_path_value = param.get('value')
                    
                    # $(find-pkg-share ...) 形式を実際のパスに変換
                    if '$(find-pkg-share simple_trajectory_generator)' in csv_path_value:
                        relative_path = csv_path_value.replace('$(find-pkg-share simple_trajectory_generator)/', '')
                        csv_path = search_base / "aichallenge/workspace/src/aichallenge_submit/simple_trajectory_generator" / relative_path
                    else:
                        csv_path = Path(csv_path_value)
                    
                    if csv_path.exists():
                        print(f"🔍 XMLから検出した経路CSV: {csv_path}")
                        return csv_path
        except Exception as e:
            print(f"⚠️ XMLの解析に失敗: {e}")
    
    # フォールバック: パターンマッチングで検索
    search_patterns = [
        "aichallenge/workspace/src/aichallenge_submit/simple_trajectory_generator/data/raceline*.csv",
    ]
    
    for pattern in search_patterns:
        csv_files = list(search_base.glob(pattern))
        if csv_files:
            csv_path = csv_files[0]
            print(f"🔍 検出した経路CSV: {csv_path}")
            return csv_path
    
    raise FileNotFoundError("Reference CSV not found")


class TrajectoryErrorAnalyzer:
    def __init__(self, rosbag_dir: str, reference_csv: str):
        self.rosbag_dir = Path(rosbag_dir)
        self.reference_path = self.load_reference_trajectory(reference_csv)
        
        self.db_path = self.rosbag_dir / 'rosbag2_autoware_0.db3'
        if not self.db_path.exists():
            raise FileNotFoundError(f"ROSbag database not found: {self.db_path}")
        
        print(f"✅ ROSbag database: {self.db_path}")
        print(f"✅ Reference trajectory: {len(self.reference_path)} points")
    
    def load_reference_trajectory(self, csv_path: str) -> np.ndarray:
        df = pd.read_csv(csv_path)
        
        if 'x' in df.columns and 'y' in df.columns:
            yaw_col = 'yaw' if 'yaw' in df.columns else df.columns[5]
            trajectory = df[['x', 'y', yaw_col]].values
        else:
            trajectory = df.iloc[:, [0, 1, 5]].values
        
        return trajectory
    
    def get_topic_id(self, conn: sqlite3.Connection, topic_name: str) -> int:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM topics WHERE name = ?", (topic_name,))
        result = cursor.fetchone()
        
        if not result:
            raise ValueError(f"Topic '{topic_name}' not found in rosbag")
        
        return result[0]
    
    def read_odometry_messages(self) -> List[Dict]:
        conn = sqlite3.connect(str(self.db_path))
        topic_id = self.get_topic_id(conn, '/localization/kinematic_state')
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT timestamp, data 
            FROM messages 
            WHERE topic_id = ? 
            ORDER BY timestamp
        """, (topic_id,))
        
        messages = []
        for timestamp, data in cursor.fetchall():
            parsed = self.parse_odometry_cdr(data)
            if parsed:
                parsed['timestamp'] = timestamp / 1e9
                messages.append(parsed)
        
        conn.close()
        print(f"✅ Loaded {len(messages)} messages")
        return messages
    
    def parse_odometry_cdr(self, cdr_data: bytes) -> Dict:
        try:
            import struct
            
            offset = 4
            offset += 8
            
            frame_id_length = struct.unpack_from('<I', cdr_data, offset)[0]
            offset += 4 + frame_id_length
            offset = (offset + 3) & ~3
            
            child_frame_id_length = struct.unpack_from('<I', cdr_data, offset)[0]
            offset += 4 + child_frame_id_length
            offset = (offset + 3) & ~3
            
            x, y, z, qx, qy, qz, qw = struct.unpack_from('<7d', cdr_data, offset)
            
            return {'x': x, 'y': y, 'z': z, 'qx': qx, 'qy': qy, 'qz': qz, 'qw': qw}
        
        except Exception as e:
            return None
    
    def quaternion_to_yaw(self, qx: float, qy: float, qz: float, qw: float) -> float:
        siny_cosp = 2 * (qw * qz + qx * qy)
        cosy_cosp = 1 - 2 * (qy * qy + qz * qz)
        return np.arctan2(siny_cosp, cosy_cosp)
    
    def calculate_lateral_error(self, actual_x: float, actual_y: float, actual_yaw: float) -> Tuple[float, float, float]:
        distances = np.sqrt(
            (self.reference_path[:, 0] - actual_x)**2 +
            (self.reference_path[:, 1] - actual_y)**2
        )
        nearest_idx = np.argmin(distances)
        nearest_distance = distances[nearest_idx]
        
        ref_x, ref_y, ref_yaw = self.reference_path[nearest_idx]
        
        dx = actual_x - ref_x
        dy = actual_y - ref_y
        
        lateral_error = -dx * np.sin(ref_yaw) + dy * np.cos(ref_yaw)
        heading_error = self.normalize_angle(actual_yaw - ref_yaw)
        
        return lateral_error, heading_error, nearest_distance
    
    def normalize_angle(self, angle: float) -> float:
        while angle > np.pi:
            angle -= 2 * np.pi
        while angle < -np.pi:
            angle += 2 * np.pi
        return angle
    
    def analyze(self) -> Dict:
        print("\n" + "="*60)
        print("📊 ROSbag解析開始")
        print("="*60)
        
        odom_messages = self.read_odometry_messages()
        
        if not odom_messages:
            raise ValueError("No Odometry messages found")
        
        lateral_errors = []
        heading_errors = []
        timestamps = []
        
        for msg in odom_messages:
            yaw = self.quaternion_to_yaw(msg['qx'], msg['qy'], msg['qz'], msg['qw'])
            lat_err, head_err, _ = self.calculate_lateral_error(msg['x'], msg['y'], yaw)
            
            lateral_errors.append(lat_err)
            heading_errors.append(head_err)
            timestamps.append(msg['timestamp'])
        
        lateral_errors = np.array(lateral_errors)
        heading_errors = np.array(heading_errors)
        
        metrics = {
            'trajectory_errors': {
                'lateral_error': {
                    'mean': float(np.mean(np.abs(lateral_errors))),
                    'max': float(np.max(np.abs(lateral_errors))),
                    'std': float(np.std(lateral_errors)),
                    'rms': float(np.sqrt(np.mean(lateral_errors**2))),
                    'percentile_95': float(np.percentile(np.abs(lateral_errors), 95))
                },
                'heading_error': {
                    'mean': float(np.mean(np.abs(heading_errors))),
                    'max': float(np.max(np.abs(heading_errors))),
                    'std': float(np.std(heading_errors)),
                    'rms': float(np.sqrt(np.mean(heading_errors**2))),
                    'percentile_95': float(np.percentile(np.abs(heading_errors), 95))
                }
            },
            'total_samples': len(lateral_errors),
            'duration_sec': float(timestamps[-1] - timestamps[0]) if timestamps else 0.0,
            'completion_rate': 1.0
        }
        
        print(f"\n✅ 解析完了")
        print(f"📏 横方向誤差: {metrics['trajectory_errors']['lateral_error']['mean']:.4f} m")
        print(f"📐 向き誤差: {metrics['trajectory_errors']['heading_error']['mean']:.4f} rad")
        print("="*60 + "\n")
        
        return metrics
    
    def save_metrics(self, metrics: Dict, output_path: str):
        output_file = Path(output_path)
        output_file.parent.mkdir(parents=True, exist_ok=True)
        
        with open(output_file, 'w') as f:
            yaml.dump(metrics, f, default_flow_style=False, sort_keys=False)
        
        print(f"💾 結果を保存: {output_path}")


def main():
    parser = argparse.ArgumentParser(description='ROSbag2から経路追従誤差を計算')
    parser.add_argument('--rosbag', default=None, help='ROSbagディレクトリ')
    parser.add_argument('--reference', default=None, help='目標経路CSV')
    parser.add_argument('--output', default=None, help='出力YAMLファイル')
    
    args = parser.parse_args()
    
    try:
        rosbag_dir = Path(args.rosbag) if args.rosbag else find_latest_rosbag()
        reference_csv = Path(args.reference) if args.reference else find_reference_csv()
        output_path = args.output if args.output else str(rosbag_dir.parent / 'trajectory_errors.yaml')
        
        analyzer = TrajectoryErrorAnalyzer(str(rosbag_dir), str(reference_csv))
        metrics = analyzer.analyze()
        analyzer.save_metrics(metrics, str(output_path))
        
        print("🎉 処理完了")
        
    except Exception as e:
        print(f"\n❌ エラー: {e}")
        import traceback
        traceback.print_exc()
        exit(1)


if __name__ == '__main__':
    main()
