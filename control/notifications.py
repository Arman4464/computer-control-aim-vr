"""
Native Toast Notification Manager (AIM-VR 3.0 Control Subsystem).
Provides native Windows Action Center toast notifications using Windows Runtime
and native FreeDesktop notifications on Linux via platform driver routing.
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
    Dispatches a native desktop notification.
    On Windows: Uses Windows Action Center toast notifications.
    On Linux: Uses FreeDesktop notify-send / D-Bus via Platform Driver.
    """
    if sys.platform != "win32":
        try:
            from control.platform import get_platform_driver
            return get_platform_driver().notifier.send_notification(
                title=title, message=message, app_id=app_id, sound=sound
            )
        except Exception as e:
            return {"status": "error", "message": str(e)}

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

        $xmlDoc = New-Object Windows.Data.Xml.Dom.XmlDocument
        $xmlDoc.LoadXml($xmlStr)

        $toast = [Windows.UI.Notifications.ToastNotification]::new($xmlDoc)
        [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier($appId).Show($toast)
        Write-Output "SUCCESS"
    }} catch {{
        Write-Error $_.Exception.Message
    }}
    """

    try:
        res = subprocess.run(
            [
                "powershell.exe",
                "-NoProfile",
                "-NonInteractive",
                "-WindowStyle", "Hidden",
                "-Command", ps_code
            ],
            capture_output=True,
            text=True,
            timeout=5.0
        )
        if res.returncode == 0 and "SUCCESS" in res.stdout:
            return {"status": "success", "message": f"Toast notification '{title}' dispatched successfully."}
        else:
            return {"status": "error", "message": f"Failed to dispatch toast: {res.stderr.strip() or res.stdout.strip()}"}
    except subprocess.TimeoutExpired:
        return {"status": "error", "message": "PowerShell toast notification timed out."}
    except Exception as e:
        return {"status": "error", "message": f"Unexpected notification error: {str(e)}"}
