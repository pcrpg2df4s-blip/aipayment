import os
import paramiko
import sys
from dotenv import load_dotenv

load_dotenv()

def main():
    hostname = os.getenv("VPS_HOST")
    username = os.getenv("VPS_USERNAME")
    password = os.getenv("VPS_PASSWORD")
    
    if not all([hostname, username, password]):
        print("Error: VPS_HOST, VPS_USERNAME, or VPS_PASSWORD not found in environment!")
        sys.exit(1)
    
    local_dir = "/Users/sav/bangen"
    remote_dir = "/root/banana"
    
    files_to_upload = [
        "utils.py",
        "main.py",
        "payment_server.py",
        "daily_report.py",
        "checker.py",
        "db.py",
        "ai.mp4",
        "agreement.html",
        "index.html",
        "trial.html",
        "script.js",
        "trial.js",
        ".env"
    ]
    
    print(f"Connecting to VPS at {hostname}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        ssh.connect(hostname, username=username, password=password, timeout=10)
        print("Connected successfully!")
        
        sftp = ssh.open_sftp()
        for filename in files_to_upload:
            local_path = os.path.join(local_dir, filename)
            remote_path = os.path.join(remote_dir, filename)
            
            print(f"Uploading {filename} to {remote_path}...")
            sftp.put(local_path, remote_path)
            print(f"Uploaded {filename} successfully.")
            
        sftp.close()
        
        # Checkpoint WAL before restarting
        print("\nCheckpointing SQLite WAL on VPS...")
        ssh.exec_command("python3 -c \"import sqlite3; conn=sqlite3.connect('/root/banana/database.sqlite'); conn.execute('PRAGMA wal_checkpoint(FULL);'); conn.close()\"")
        
        # Restart services
        print("\nRestarting systemd services on VPS...")
        commands = [
            "systemctl restart banana-bot",
            "systemctl restart banana-payment",
            "sleep 3",
            "systemctl status banana-bot --no-pager -n 10",
            "systemctl status banana-payment --no-pager -n 10"
        ]
        
        full_command = " && ".join(commands)
        stdin, stdout, stderr = ssh.exec_command(full_command)
        
        print("\n=== Command Output ===")
        print(stdout.read().decode('utf-8'))
        
        err = stderr.read().decode('utf-8')
        if err:
            print("\n=== Errors ===")
            print(err)
            
        ssh.close()
        print("\nDeployment completed successfully!")
    except Exception as e:
        print(f"Deployment failed: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
