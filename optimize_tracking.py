#!/usr/bin/env python3
"""
optimize_tracking.py - メイン最適化スクリプト
"""

import argparse
import optuna
from pathlib import Path
import yaml
import sys

sys.path.append('src')
from config_writer import ReferenceConfigWriter
from simulation_runner import run_simulation
from trajectory_error_analyzer import TrajectoryErrorAnalyzer, find_latest_rosbag, find_reference_csv


class OptimizationManager:
    def __init__(self, args):
        self.args = args
        self.target_vel = args.target_vel
        self.base_config_path = Path(args.base_config)
        
        if args.reference:
            self.reference_csv = str(Path(args.reference).resolve())
        else:
            self.reference_csv = str(find_reference_csv().resolve())
        
        print(f"\n📍 使用する経路ファイル: {self.reference_csv}")
        self._display_csv_info()
        
        study_name = f'autoware_tracking_vel{self.target_vel}'
        self.study = optuna.create_study(
            direction='minimize',
            study_name=study_name,
            storage='sqlite:///results/optuna_study.db',
            load_if_exists=True
        )
        
        self.config_writer = ReferenceConfigWriter(
            base_config_path=self.base_config_path,
            fixed_params={
                'external_target_vel': self.target_vel,
                'csv_path': self.reference_csv
            }
        )
        
        if not args.resume:
            self.backup_path = self.config_writer.backup_config()
    
    def _display_csv_info(self):
        csv_path = Path(self.reference_csv)
        if csv_path.exists():
            import pandas as pd
            try:
                df = pd.read_csv(csv_path)
                print(f"📊 経路ポイント数: {len(df)} points")
                if 'speed' in df.columns:
                    print(f"🏎️  速度範囲: {df['speed'].min():.2f} - {df['speed'].max():.2f} m/s")
            except Exception as e:
                print(f"⚠️  CSV読み込み警告: {e}")
    
    def define_search_space(self, trial: optuna.Trial) -> dict:
        params = {
            'lookahead_gain': trial.suggest_float('lookahead_gain', 0.3, 3.0),
            'lookahead_min_distance': trial.suggest_float('lookahead_min_distance', 1.0, 8.0),
            'speed_proportional_gain': trial.suggest_float('speed_proportional_gain', 0.5, 3.0),
        }
        return params
    
    def calculate_objective(self, metrics: dict) -> float:
        if metrics.get('completion_rate', 0) < 0.95:
            return 10000.0
        
        lateral_mean = metrics['trajectory_errors']['lateral_error']['mean']
        lateral_max = metrics['trajectory_errors']['lateral_error']['max']
        heading_mean = metrics['trajectory_errors']['heading_error']['mean']
        heading_max = metrics['trajectory_errors']['heading_error']['max']
        
        objective = (
            lateral_mean * 1.0 +
            lateral_max * 0.2 +
            heading_mean * 0.3 +
            heading_max * 0.1
        )
        
        return objective
    
    def objective(self, trial: optuna.Trial) -> float:
        print(f"\n{'='*60}")
        print(f"🔬 Trial {trial.number} 開始")
        print(f"{'='*60}")
        
        params = self.define_search_space(trial)
        print(f"\n📊 サンプリングされたパラメータ:")
        for key, value in params.items():
            print(f"   {key}: {value:.4f}")
        
        print(f"\n📝 設定ファイルを更新中...")
        self.config_writer.write_config(params, trial_id=None)

        # 再ビルド設定
        if self.args.no_rebuild:
            # --no-rebuildオプション指定時は全てのtrialで再ビルドしない
            rebuild = False
        else:
            # デフォルト：最初のtrialだけ完全再ビルド（CSVファイルの変更を反映）
            rebuild = (trial.number == 0)

        success = run_simulation(trial.number, timeout=self.args.timeout, rebuild=rebuild)
        
        if not success:
            print(f"❌ Trial {trial.number}: シミュレーション失敗")
            return 10000.0
        
        print(f"\n📊 ROSbagを解析中...")
        try:
            rosbag_dir = find_latest_rosbag()
            analyzer = TrajectoryErrorAnalyzer(str(rosbag_dir), self.reference_csv)
            metrics = analyzer.analyze()
            
            output_yaml = rosbag_dir.parent / 'trajectory_errors.yaml'
            analyzer.save_metrics(metrics, str(output_yaml))
            
        except Exception as e:
            print(f"❌ Trial {trial.number}: 解析失敗 - {e}")
            return 10000.0
        
        objective_value = self.calculate_objective(metrics)
        
        trial.set_user_attr('target_vel', self.target_vel)
        trial.set_user_attr('csv_path', self.reference_csv)
        trial.set_user_attr('lateral_error_mean', metrics['trajectory_errors']['lateral_error']['mean'])
        trial.set_user_attr('lateral_error_max', metrics['trajectory_errors']['lateral_error']['max'])
        trial.set_user_attr('heading_error_mean', metrics['trajectory_errors']['heading_error']['mean'])
        trial.set_user_attr('heading_error_max', metrics['trajectory_errors']['heading_error']['max'])
        trial.set_user_attr('duration_sec', metrics['duration_sec'])
        
        print(f"\n{'='*60}")
        print(f"✅ Trial {trial.number} 完了")
        print(f"🎯 目的関数値: {objective_value:.4f}")
        print(f"📏 横方向誤差: {metrics['trajectory_errors']['lateral_error']['mean']:.4f} m")
        print(f"📐 向き誤差: {metrics['trajectory_errors']['heading_error']['mean']:.4f} rad")
        print(f"{'='*60}\n")
        
        return objective_value
    
    def optimize(self):
        print(f"\n{'='*60}")
        print(f"🚀 経路追従パラメータ最適化開始")
        print(f"{'='*60}")
        print(f"目標速度: {self.target_vel} m/s")
        print(f"試行回数: {self.args.trials}")
        print(f"タイムアウト: {self.args.timeout}秒")
        print(f"{'='*60}\n")
        
        try:
            self.study.optimize(
                self.objective,
                n_trials=self.args.trials,
                n_jobs=1,
                show_progress_bar=False
            )
            
            self.save_results()
            
        finally:
            if hasattr(self, 'backup_path'):
                self.config_writer.restore_config(self.backup_path)
    
    def save_results(self):
        results_dir = Path('results')
        results_dir.mkdir(exist_ok=True)
        
        best_params = self.study.best_params.copy()
        best_params['external_target_vel'] = self.target_vel
        best_params['csv_path'] = self.reference_csv
        best_params['best_value'] = self.study.best_value
        
        best_config_path = results_dir / f'best_config_vel{self.target_vel}.yaml'
        with open(best_config_path, 'w') as f:
            yaml.dump(best_params, f, default_flow_style=False)
        
        print(f"\n{'='*60}")
        print(f"🎉 最適化完了！")
        print(f"{'='*60}")
        print(f"✨ 最良目的関数値: {self.study.best_value:.4f}")
        print(f"\n📊 最適パラメータ:")
        for key, value in best_params.items():
            if key not in ['best_value', 'csv_path', 'external_target_vel']:
                print(f"   {key}: {value:.4f}")
        print(f"\n💾 設定ファイル: {best_config_path}")
        print(f"{'='*60}\n")
        
        if len(self.study.trials) > 1:
            first_value = self.study.trials[0].value
            best_value = self.study.best_value
            improvement = ((first_value - best_value) / first_value) * 100
            print(f"📈 改善度: {improvement:.2f}%")


def parse_args():
    parser = argparse.ArgumentParser(description='経路追従パラメータ最適化')
    parser.add_argument('--target-vel', type=float, required=True, help='目標速度 [m/s]')
    parser.add_argument('--trials', type=int, default=10, help='試行回数')
    parser.add_argument('--timeout', type=int, default=600, help='タイムアウト [秒]')
    parser.add_argument('--base-config', type=str,
                       default='aichallenge/workspace/src/aichallenge_submit/aichallenge_submit_launch/launch/reference.launch.xml',
                       help='reference.launch.xmlのパス')
    parser.add_argument('--reference', type=str, default=None, help='経路CSVファイル')
    parser.add_argument('--resume', action='store_true', help='既存studyを続行')
    parser.add_argument('--no-rebuild', action='store_true', help='Dockerイメージを再ビルドしない（高速化）')
    return parser.parse_args()


def main():
    args = parse_args()
    
    if args.target_vel <= 0:
        print("❌ Error: target_vel must be positive")
        sys.exit(1)
    
    manager = OptimizationManager(args)
    manager.optimize()
    
    print("\n🎊 全ての処理が完了しました！")
    print("📊 結果確認: optuna-dashboard sqlite:///results/optuna_study.db")


if __name__ == '__main__':
    main()
