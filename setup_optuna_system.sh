#!/bin/bash
# Optuna最適化システムのセットアップスクリプト

echo "======================================"
echo "🚀 Optuna最適化システムのセットアップ"
echo "======================================"

# 1. 必要なディレクトリの作成
echo ""
echo "📁 ディレクトリを作成中..."
mkdir -p src
mkdir -p results
mkdir -p config/trials
mkdir -p submit

# 2. Python依存パッケージのインストール
echo ""
echo "📦 Python依存パッケージをインストール中..."
echo "   必要なパッケージ: optuna, pandas, numpy, pyyaml"

if command -v pip3 &> /dev/null; then
    pip3 install --user optuna pandas numpy pyyaml
elif command -v pip &> /dev/null; then
    pip install --user optuna pandas numpy pyyaml
else
    echo "❌ エラー: pipが見つかりません"
    echo "   以下のコマンドで手動インストールしてください："
    echo "   pip install optuna pandas numpy pyyaml"
    exit 1
fi

# 3. 環境チェック
echo ""
echo "🔍 環境をチェック中..."

# プロジェクトルートにいるか確認
if [ ! -f "docker_build.sh" ] || [ ! -f "docker_run.sh" ]; then
    echo "⚠️  警告: docker_build.shまたはdocker_run.shが見つかりません"
    echo "   aichallenge-2025プロジェクトのルートディレクトリで実行してください"
fi

# aichallengeディレクトリが存在するか確認
if [ ! -d "aichallenge/workspace/src/aichallenge_submit" ]; then
    echo "⚠️  警告: aichallenge/workspace/src/aichallenge_submitが見つかりません"
    echo "   プロジェクト構造を確認してください"
fi

# reference.launch.xmlが存在するか確認
if [ ! -f "aichallenge/workspace/src/aichallenge_submit/aichallenge_submit_launch/launch/reference.launch.xml" ]; then
    echo "❌ エラー: reference.launch.xmlが見つかりません"
    echo "   パス: aichallenge/workspace/src/aichallenge_submit/aichallenge_submit_launch/launch/reference.launch.xml"
    exit 1
fi

# 4. Pythonファイルの存在確認
echo ""
echo "📝 必要なファイルをチェック中..."

required_files=(
    "optimize_tracking.py"
    "src/config_writer.py"
    "src/simulation_runner.py"
    "src/trajectory_error_analyzer.py"
)

missing_files=()
for file in "${required_files[@]}"; do
    if [ -f "$file" ]; then
        echo "   ✅ $file"
    else
        echo "   ❌ $file が見つかりません"
        missing_files+=("$file")
    fi
done

if [ ${#missing_files[@]} -gt 0 ]; then
    echo ""
    echo "❌ エラー: 必要なファイルが不足しています"
    echo "   以下のファイルをプロジェクトルートにコピーしてください："
    for file in "${missing_files[@]}"; do
        echo "   - $file"
    done
    exit 1
fi

# 5. Docker環境の確認
echo ""
echo "🐳 Docker環境をチェック中..."
if command -v docker &> /dev/null; then
    echo "   ✅ Dockerがインストールされています"
    docker --version
else
    echo "   ❌ エラー: Dockerがインストールされていません"
    exit 1
fi

if command -v rocker &> /dev/null; then
    echo "   ✅ rockerがインストールされています"
else
    echo "   ⚠️  警告: rockerがインストールされていません"
    echo "   インストール方法: pip install rocker"
fi

# 6. 完了メッセージ
echo ""
echo "======================================"
echo "✅ セットアップ完了！"
echo "======================================"
echo ""
echo "📖 使い方："
echo ""
echo "1. 最適化を実行："
echo "   python3 optimize_tracking.py --target-vel 3.0 --trials 10"
echo ""
echo "2. 結果を確認："
echo "   optuna-dashboard sqlite:///results/optuna_study.db"
echo ""
echo "3. 高速モード（2回目以降）："
echo "   python3 optimize_tracking.py --target-vel 3.0 --trials 10 --resume --no-rebuild"
echo ""
echo "======================================"
