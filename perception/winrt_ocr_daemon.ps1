Add-Type -AssemblyName System.Runtime.WindowsRuntime
[void][Windows.Media.Ocr.OcrEngine, Windows.Foundation, ContentType = WindowsRuntime]
[void][Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType = WindowsRuntime]
[void][Windows.Storage.StorageFile, Windows.Storage, ContentType = WindowsRuntime]

function Await-WinRT($asyncOp, $type) {
    $awaiter = [WindowsRuntimeSystemExtensions].GetMember('GetAwaiter', 'Method', 'Public,Static') | 
        Where-Object { $_.GetParameters()[0].ParameterType.Name -eq 'IAsyncOperation`1' } | 
        Select-Object -First 1
    return $awaiter.MakeGenericMethod($type).Invoke($null, @($asyncOp)).GetResult()
}

$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromUserProfileLanguages()
if ($null -eq $engine) {
    $lang = New-Object Windows.Globalization.Language("en-US")
    $engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($lang)
}

[Console]::Out.WriteLine("READY")
[Console]::Out.Flush()

while ($line = [Console]::In.ReadLine()) {
    if ([string]::IsNullOrWhiteSpace($line) -or $line -eq "EXIT") {
        break
    }
    $stream = $null
    try {
        $path = $line.Trim()
        if (-not (Test-Path $path)) {
            [Console]::Out.WriteLine('{"status":"error","message":"file not found"}')
            [Console]::Out.Flush()
            continue
        }
        $file = Await-WinRT ([Windows.Storage.StorageFile]::GetFileFromPathAsync($path)) ([Windows.Storage.StorageFile])
        $stream = Await-WinRT ($file.OpenReadAsync()) ([Windows.Storage.Streams.IRandomAccessStreamWithContentType])
        $decoder = Await-WinRT ([Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)) ([Windows.Graphics.Imaging.BitmapDecoder])
        $sb = Await-WinRT ($decoder.GetSoftwareBitmapAsync()) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $ocrResult = Await-WinRT ($engine.RecognizeAsync($sb)) ([Windows.Media.Ocr.OcrResult])

        $words = @()
        foreach ($l in $ocrResult.Lines) {
            foreach ($w in $l.Words) {
                $words += @{
                    text = $w.Text
                    x = [int]$w.BoundingRect.X
                    y = [int]$w.BoundingRect.Y
                    w = [int]$w.BoundingRect.Width
                    h = [int]$w.BoundingRect.Height
                }
            }
        }
        # Force array encapsulation to prevent single-element flattening in PS 5.1
        $wordsOut = @($words)
        $json = ConvertTo-Json -Depth 10 -Compress @{ status = "ok"; text = $ocrResult.Text; words = $wordsOut }
        [Console]::Out.WriteLine($json)
        [Console]::Out.Flush()
    } catch {
        $cleanMsg = $_.Exception.Message.Replace("`r", " ").Replace("`n", " ").Replace('"', '\"')
        [Console]::Out.WriteLine("{`"status`":`"error`",`"message`":`"$cleanMsg`"}")
        [Console]::Out.Flush()
    } finally {
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
}
