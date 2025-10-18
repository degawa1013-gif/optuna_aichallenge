#!/usr/bin/env python3
"""
simulation_runner.py - Dockerビルド&実行モジュール
"""

import subprocess
import time
import threading
import sys
from pathlib import Path


def spinner_animation(message: str, stop_event: threading.Event):
    """スピナーアニメーション表示"""
    spinner_chars = ['⠋', '⠙', '⠹', '⠸', '⠼', '⠴', '⠦', '⠧', '⠇', '⠏']
    idx = 0
    while not stop_event.is_set():
        sys.stdout.write(f'\r{message} {spinner_chars[idx]}')
        sys.stdout.flush()
        idx = (idx + 1) % len(spinner_chars)
        time.sleep(0.1)
    sys.stdout.write('\r' + ' ' * (len(message) + 2) + '\r')
    sys.stdout.flush()


def run_with_spinner(cmd: list, message: str, timeout: int = None, **kwargs):
    stop_event = threading.Event()
    spinner_thread = threading.Thread(target=spinner_animation, args=(message, stop_event))
    spinner_thread.start()
    
    try:
        result = subprocess.run(cmd, timeout=timeout, **kwargs)
        return result
    finally:
        stop_event.set()
        spinner_thread.join()


def run_simulation(trial_id: int, timeout: int = 600, rebuild: bool = True, force_clean: bool = False) -> bool:
    print(f"\n{'='*60}")
    print(f"🚗 Trial {trial_id}: シミュレーション実行")
    print(f"{'='*60}")

    # rebuildフラグに応じて処理を分岐
    if rebuild or force_clean:
        # submit/aichallenge_submit.tar.gzを再作成（重要！）
        print("📦 aichallenge_submit.tar.gzを再作成...")
        submit_dir = Path("submit")
        submit_dir.mkdir(exist_ok=True)
        
        # 古いtar.gzを削除
        old_tar = submit_dir / "aichallenge_submit.tar.gz"
        if old_tar.exists():
            old_tar.unlink()
        
        # 新しいtar.gzを作成
        tar_result = subprocess.run([
            'tar', 'czf',
            'submit/aichallenge_submit.tar.gz',
            '-C', 'aichallenge/workspace/src',
            'aichallenge_submit'
        ], capture_output=True, text=True, check=False)

        if tar_result.returncode == 0:
            print("   ✅ tar.gz作成完了")

            # tar.gz内のCSVファイルを確認（デバッグ）
            csv_check_result = subprocess.run([
                'tar', '-tzf', 'submit/aichallenge_submit.tar.gz',
                'aichallenge_submit/simple_trajectory_generator/data/raceline_awsim_30km_from_garage.csv'
            ], capture_output=True, text=True, check=False)

            if csv_check_result.returncode == 0:
                # CSVの行数をカウント
                csv_lines_result = subprocess.run([
                    'bash', '-c',
                    'tar -xzOf submit/aichallenge_submit.tar.gz aichallenge_submit/simple_trajectory_generator/data/raceline_awsim_30km_from_garage.csv | wc -l'
                ], capture_output=True, text=True, check=False)

                if csv_lines_result.returncode == 0:
                    lines = csv_lines_result.stdout.strip()
                    print(f"   📊 tar.gz内のCSV行数: {lines}行")
        else:
            print(f"   ⚠️ tar.gz作成に失敗: {tar_result.stderr}")
        
        # ホスト側のinstall, build, logディレクトリを削除
        print("🗑️  ホスト側のビルドディレクトリを削除...")
        for dir_name in ['install', 'build', 'log']:
            dir_path = Path(f"aichallenge/workspace/{dir_name}")
            if dir_path.exists():
                import shutil
                shutil.rmtree(dir_path, ignore_errors=True)
                print(f"   削除: {dir_path}")
        
        # 古いDockerイメージを削除
        print("🗑️  既存Dockerイメージを削除...")
        subprocess.run(['docker', 'rmi', '-f', 'aichallenge-2025-eval-natc'], 
                      capture_output=True, text=True, check=False)
        
        # ビルドキャッシュも削除
        print("🧹 ビルドキャッシュをクリア...")
        subprocess.run(['docker', 'builder', 'prune', '-f'], 
                      capture_output=True, text=True, check=False)
        
        # Docker build
        print("📦 Docker imageをビルド中（完全再ビルド）...")
        print("⚠️  CSVファイルの変更を反映するため完全再ビルドします")
        
        build_result = run_with_spinner(
            ['./docker_build.sh', 'eval'],
            "Building Docker image",
            timeout=1800,
            capture_output=True,
            text=True
        )
        
        if build_result.returncode != 0:
            print(f"❌ Docker build failed")
            print(f"Error: {build_result.stderr}")
            return False
        
        print("✅ Docker build 完了")
    else:
        # rebuild=Falseの時：既存イメージの存在を確認
        print("⏭️  Docker buildをスキップ（既存イメージを使用）")

        # イメージが存在するか確認
        check_image = subprocess.run(
            ['docker', 'images', '-q', 'aichallenge-2025-eval-natc'],
            capture_output=True, text=True, check=False
        )

        if not check_image.stdout.strip():
            print("❌ エラー: Dockerイメージが存在しません")
            print("   Trial 0でイメージをビルドするか、手動でビルドしてください：")
            print("   ./docker_build.sh eval")
            return False
        else:
            print(f"   ✅ 既存イメージを確認: aichallenge-2025-eval-natc")

    # Docker run前に、更新されたXMLファイルをコンテナにコピーするための準備
    # outputディレクトリに更新されたXMLをコピー（docker_run.shがマウントする）
    print("📝 更新されたXMLファイルを準備中...")
    xml_source = Path("aichallenge/workspace/src/aichallenge_submit/aichallenge_submit_launch/launch/reference.launch.xml")
    xml_staging = Path("output/reference.launch.xml")
    if xml_source.exists():
        import shutil
        shutil.copy2(xml_source, xml_staging)
        print(f"   ✅ XMLファイルをステージング: {xml_staging}")

    # Docker run
    print("🏁 シミュレーション実行中...")
    run_result = run_with_spinner(
        ['./docker_run.sh', 'eval', 'cpu'],
        f"Running simulation (timeout: {timeout}s)",
        timeout=timeout,
        capture_output=True,
        text=True
    )
    
    if run_result.returncode != 0:
        print(f"❌ Simulation failed or timeout")
        return False
    
    print("✅ シミュレーション完了")
    
    return True
