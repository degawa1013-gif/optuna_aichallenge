#!/usr/bin/env python3
"""
config_writer.py - XMLパラメータ書き換えモジュール
reference.launch.xmlのパラメータを動的に更新
"""

import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Dict, Union
import shutil


class ReferenceConfigWriter:
    """reference.launch.xmlファイルの書き換えクラス"""
    
    def __init__(self, base_config_path: str, fixed_params: Dict[str, Union[float, str]] = None):
        """
        Args:
            base_config_path: ベースとなるreference.launch.xmlのパス
            fixed_params: 固定パラメータ（例: {'external_target_vel': 3.0, 'csv_path': '...'}）
        """
        self.base_config_path = Path(base_config_path)
        self.fixed_params = fixed_params or {}
        
        if not self.base_config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.base_config_path}")
        
        print(f"✅ Config loaded: {self.base_config_path}")
    
    def write_config(self, optimizable_params: Dict[str, float], trial_id: int = None) -> Path:
        """
        パラメータを反映した設定ファイルを生成
        
        Args:
            optimizable_params: Optunaが最適化するパラメータ
            trial_id: Trial番号（Noneの場合は元ファイルを直接上書き）
        
        Returns:
            生成された設定ファイルのパス
        """
        # XMLを読み込み
        tree = ET.parse(self.base_config_path)
        root = tree.getroot()
        
        # 全パラメータを統合
        all_params = {**self.fixed_params, **optimizable_params}
        
        # パラメータを更新
        for param_name, param_value in all_params.items():
            updated = self._update_param(root, param_name, param_value)
            if updated:
                if param_name == 'csv_path':
                    print(f"  ✓ {param_name} = {param_value}")
                else:
                    print(f"  ✓ {param_name} = {param_value:.4f}")
            else:
                print(f"  ⚠️  Parameter '{param_name}' not found in XML")
        
        # 出力先を決定
        if trial_id is not None:
            output_dir = Path('config/trials')
            output_dir.mkdir(parents=True, exist_ok=True)
            output_path = output_dir / f'reference_trial{trial_id}.xml'
        else:
            output_path = self.base_config_path
        
        # XMLを保存
        tree.write(output_path, encoding='utf-8', xml_declaration=True)
        
        return output_path
    
    def _update_param(self, root: ET.Element, param_name: str, param_value: Union[float, str]) -> bool:
        """
        XMLツリー内のパラメータを更新
        
        Returns:
            True if parameter was found and updated, False otherwise
        """
        # csv_pathの特別な処理（絶対パスをROS2パッケージパス形式に変換）
        if param_name == 'csv_path':
            param_value_str = str(param_value)
            
            # simple_trajectory_generator/data/ 以降のファイル名を抽出
            if 'simple_trajectory_generator/data/' in param_value_str:
                filename = param_value_str.split('simple_trajectory_generator/data/')[-1]
                # ROS2のパッケージパス形式に変換（Docker内で動作する）
                ros_path = f"$(find-pkg-share simple_trajectory_generator)/data/{filename}"
            else:
                ros_path = param_value_str
            
            # <node pkg="simple_trajectory_generator"> 内の <param name="csv_path"> を探す
            for node in root.findall(".//node[@pkg='simple_trajectory_generator']"):
                for param in node.findall(".//param[@name='csv_path']"):
                    param.set('value', ros_path)
                    return True
            return False
        
        # 数値パラメータの処理
        param_value_str = str(param_value)
        
        # <param name="パラメータ名" value="値"/> を探して更新
        for param in root.findall(f".//param[@name='{param_name}']"):
            param.set('value', param_value_str)
            return True
        
        # <arg name="パラメータ名" value="値"/> も探す
        for arg in root.findall(f".//arg[@name='{param_name}']"):
            arg.set('value', param_value_str)
            return True
        
        # <let name="パラメータ名" value="値"/> も探す
        for let in root.findall(f".//let[@name='{param_name}']"):
            let.set('value', param_value_str)
            return True
        
        return False
    
    def backup_config(self, backup_suffix: str = '.backup') -> Path:
        """設定ファイルのバックアップを作成"""
        backup_path = Path(str(self.base_config_path) + backup_suffix)
        shutil.copy2(self.base_config_path, backup_path)
        print(f"📦 Backup created: {backup_path}")
        return backup_path
    
    def restore_config(self, backup_path: Path):
        """バックアップから設定ファイルを復元"""
        if backup_path.exists():
            shutil.copy2(backup_path, self.base_config_path)
            print(f"♻️  Config restored from: {backup_path}")
        else:
            print(f"⚠️  Backup not found: {backup_path}")
