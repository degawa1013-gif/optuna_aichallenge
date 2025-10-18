# Optuna経路追従パラメータ最適化システム

ROS2 Autowareの経路追従パラメータをOptunaで自動最適化するシステムです。

## 📁 必要なファイル

### Pythonファイル（4つ）
```
optimize_tracking.py              # メインスクリプト
src/config_writer.py              # XMLパラメータ書き換え
src/simulation_runner.py          # Dockerビルド&実行
src/trajectory_error_analyzer.py  # ROSbag解析
```

### セットアップスクリプト
```
setup_optuna_system.sh            # セットアップスクリプト
OPTUNA_README.md                  # このファイル
```

---

## 🚀 別のPCでのセットアップ手順

### 1. ファイルのコピー

**方法A: 手動コピー**
```bash
# aichallenge-2025プロジェクトのルートディレクトリで
# 以下のファイルを新しいPCにコピー：
├── optimize_tracking.py
├── src/
│   ├── config_writer.py
│   ├── simulation_runner.py
│   └── trajectory_error_analyzer.py
├── setup_optuna_system.sh
└── OPTUNA_README.md
```

**方法B: tarで一括コピー（推奨）**
```bash
# 現在のPCで実行（パッケージ作成）
cd ~/aichallenge-2025
tar czf optuna_system.tar.gz \
    optimize_tracking.py \
    src/config_writer.py \
    src/simulation_runner.py \
    src/trajectory_error_analyzer.py \
    setup_optuna_system.sh \
    OPTUNA_README.md

# 新しいPCで実行（展開）
cd ~/aichallenge-2025  # 新しいPCのプロジェクトルート
tar xzf optuna_system.tar.gz
```

### 2. セットアップスクリプトの実行
```bash
cd ~/aichallenge-2025
chmod +x setup_optuna_system.sh
./setup_optuna_system.sh
```

このスクリプトが自動的に：
- 必要なディレクトリを作成
- Python依存パッケージをインストール
- 環境をチェック

### 3. 動作確認
```bash
# テスト実行（1回だけ）
python3 optimize_tracking.py --target-vel 3.0 --trials 1
```

---

## 📝 使い方

### 基本的な使い方
```bash
# 速度3.0m/sで10回最適化
python3 optimize_tracking.py --target-vel 3.0 --trials 10
```

### オプション
```bash
--target-vel FLOAT    # 目標速度 [m/s] (必須)
--trials INT          # 試行回数 (デフォルト: 10)
--timeout INT         # タイムアウト [秒] (デフォルト: 600)
--reference PATH      # 経路CSVファイル (省略時は自動検出)
--resume              # 既存studyを続行
--no-rebuild          # Dockerイメージを再ビルドしない（高速化）
```

### 実用例

**1. 初回実行（完全再ビルド）**
```bash
python3 optimize_tracking.py --target-vel 3.0 --trials 10
```
- Trial 0: 完全再ビルド（10-15分）
- Trial 1-9: 高速実行（各2-5分）

**2. 続きから実行**
```bash
python3 optimize_tracking.py --target-vel 3.0 --trials 10 --resume
```

**3. 高速モード（再ビルドなし）**
```bash
# 既にDockerイメージがある場合
python3 optimize_tracking.py --target-vel 3.0 --trials 10 --no-rebuild
```

**4. 特定の経路ファイルを使用**
```bash
python3 optimize_tracking.py --target-vel 3.0 --trials 10 \
    --reference aichallenge/workspace/src/aichallenge_submit/simple_trajectory_generator/data/my_raceline.csv
```

---

## 📊 結果の確認

### 1. YAMLファイルで確認
```bash
cat results/best_config_vel3.0.yaml
```

### 2. Optuna Dashboardで確認
```bash
# dashboardのインストール（初回のみ）
pip install optuna-dashboard

# ダッシュボード起動
optuna-dashboard sqlite:///results/optuna_study.db
```
ブラウザで http://localhost:8080 を開く

---

## 🔧 トラブルシューティング

### Q: Dockerイメージが見つからないエラー
```
❌ エラー: Dockerイメージが存在しません
```

**解決策:**
```bash
# 手動でビルド
./docker_build.sh eval

# または、Trial 0から実行
python3 optimize_tracking.py --target-vel 3.0 --trials 1
```

### Q: 経路ファイルの変更が反映されない
**解決策:**
```bash
# Dockerイメージを削除して再ビルド
docker rmi -f aichallenge-2025-eval-natc
python3 optimize_tracking.py --target-vel 3.0 --trials 1
```

### Q: シミュレーションが遅い
**解決策:**
```bash
# Trial 0だけ再ビルド、以降は高速モード
python3 optimize_tracking.py --target-vel 3.0 --trials 1
python3 optimize_tracking.py --target-vel 3.0 --trials 9 --resume --no-rebuild
```

---

## 📦 最適化されるパラメータ

| パラメータ名 | 範囲 | 説明 |
|-------------|------|------|
| `lookahead_gain` | 0.3 - 3.0 | 先読み距離のゲイン |
| `lookahead_min_distance` | 1.0 - 8.0 | 最小先読み距離 [m] |
| `speed_proportional_gain` | 0.5 - 3.0 | 速度比例ゲイン |

**固定パラメータ:**
- `steering_tire_angle_gain`: 最適化しない（XMLの値を使用）
- `external_target_vel`: コマンドライン引数で指定
- `csv_path`: 経路ファイルパス

---

## 🎯 目的関数

横方向誤差と向き誤差の重み付き合計を最小化：

```
目的関数 = lateral_mean × 1.0
         + lateral_max × 0.2
         + heading_mean × 0.3
         + heading_max × 0.1
```

完走率95%未満の場合はペナルティ（10000.0）

---

## 🔄 システムフロー

```
1. パラメータサンプリング（Optuna）
    ↓
2. reference.launch.xml更新
    ↓
3. tar.gz作成（CSVファイル含む）
    ↓
4. Docker完全再ビルド（Trial 0のみ）
    ↓
5. シミュレーション実行
    ↓
6. ROSbag解析
    ↓
7. 目的関数計算
    ↓
8. Optunaに結果を返す
```

---

## 📂 ディレクトリ構造

```
aichallenge-2025/
├── optimize_tracking.py           # メインスクリプト
├── src/
│   ├── config_writer.py
│   ├── simulation_runner.py
│   └── trajectory_error_analyzer.py
├── results/
│   ├── optuna_study.db             # Optunaデータベース
│   └── best_config_vel3.0.yaml     # 最適パラメータ
├── config/
│   └── trials/                     # trial別設定ファイル（オプション）
├── submit/
│   └── aichallenge_submit.tar.gz   # 自動生成されるtar.gz
└── output/
    └── */
        ├── rosbag/                 # ROSbagデータ
        └── trajectory_errors.yaml  # 解析結果
```

---

## 📌 注意事項

1. **CSVファイルの変更を反映する場合**
   - Trial 0で完全再ビルドが実行されます
   - または、手動で `docker rmi -f aichallenge-2025-eval-natc` してから実行

2. **パラメータ調整のみの場合**
   - `--no-rebuild` オプションで高速化できます
   - ただし、CSVファイルの変更は反映されません

3. **複数の速度で最適化する場合**
   - 各速度ごとに別のstudyが作成されます
   - `results/best_config_vel3.0.yaml`, `results/best_config_vel5.0.yaml` など

---

## 📞 サポート

問題が発生した場合は、セットアップスクリプトを実行して環境をチェックしてください：

```bash
./setup_optuna_system.sh
```
