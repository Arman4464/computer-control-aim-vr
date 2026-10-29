"""
Native Windows Toast Notification Manager (AIM-VR 3.0 Control Subsystem).
Provides native Windows Action Center toast notifications using Windows Runtime
Windows.UI.Notifications.ToastNotificationManager with XML template payloads.
"""

import subprocess
import os
import sys
import base64
import xml.sax.saxutils as saxutils
from typing import Optional, Dict, Any


def send_toast_notification(
    title: str,
    message: str,
    app_id: Optional[str] = None,
    sound: bool = True
) -> Dict[str, Any]:
    """
    Dispatches a native Windows toast notification to the Windows Action Center.

    Args:
        title: Notification header / title.
        message: Notification body / text.
        app_id: Registered Windows AppUserModelID. Defaults to Windows PowerShell or Explorer.
        sound: Whether to play the standard notification sound.

    Returns:
        {"status": "success" | "error", "message": str}
    """
    if not title and not message:
        return {"status": "error", "message": "Title or message must be provided."}

    # Default to standard Windows app IDs if none provided
    default_app_ids = [
        app_id,
        "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}\\WindowsPowerShell\\v1.0\\powershell.exe",
        "Microsoft.Windows.Explorer",
        "Microsoft.Windows.ShellExperienceHost_cw5n1h2txyewy!App",
    ]
    target_app_id = next((aid for aid in default_app_ids if aid), "Microsoft.Windows.Explorer")

    clean_title = saxutils.escape(title or "AIM-VR Notification")
    clean_message = saxutils.escape(message or "")
    audio_tag = '<audio silent="false" />' if sound else '<audio silent="true" />'

    raw_xml = f"""<toast><visual><binding template="ToastGeneric"><text>{clean_title}</text><text>{clean_message}</text></binding></visual>{audio_tag}</toast>"""
    xml_b64 = base64.b64encode(raw_xml.encode("utf-8")).decode("ascii")
    app_id_b64 = base64.b64encode(target_app_id.encode("utf-8")).decode("ascii")

    ps_code = f"""
    try {{
        [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null
        [Windows.Data.Xml.Dom.XmlDocument, Windows.Data.Xml.Dom.XmlDocument, ContentType = WindowsRuntime] | Out-Null

        $xmlStr = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{xml_b64}'))
        $appId = [System.Text.Encoding]::UTF8.GetString([System.Convert]::FromBase64String('{app_id_b64}'))

        $xml = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xml.LoadXml($xmlStr)
        $notifier = [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId)
        $toast = New-Object Windows.UI.Notifications.ToastNotification $xml
        $notifier.Show($toast)
        Write-Output "SUCCESS"
    }} catch {{
        Write-Error $_.Exception.Message
    }}
    """

    try:
        # PowerShell 5.1 (powershell.exe) has full WinRT projection support on Windows 10 & 11
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_code],
            capture_output=True,
            text=True,
            timeout=5.0
        )
        if proc.returncode == 0 and "SUCCESS" in proc.stdout:
            return {
                "status": "success",
                "message": f"Toast notification sent: '{title}'",
                "app_id": target_app_id
            }
        else:
            err = proc.stderr.strip() or proc.stdout.strip()
            return {"status": "error", "message": f"PowerShell Toast failed: {err}"}
    except Exception as e:
        return {"status": "error", "message": f"Failed to dispatch toast: {e}"}
