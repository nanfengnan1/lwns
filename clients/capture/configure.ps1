param([Parameter(Mandatory=$true)][string]$InputPath, [Parameter(Mandatory=$true)][string]$OutputPath)
$ErrorActionPreference = 'Stop'
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$settings = Get-Content -LiteralPath $InputPath -Raw -Encoding UTF8 | ConvertFrom-Json
$form = New-Object System.Windows.Forms.Form
$form.Text = 'lwns · 本地抓包设置'
$form.ClientSize = New-Object System.Drawing.Size(740, 570)
$form.StartPosition = 'CenterScreen'
$form.Font = New-Object System.Drawing.Font('Microsoft YaHei UI', 9)
$form.AutoScaleMode = [System.Windows.Forms.AutoScaleMode]::Dpi
$form.FormBorderStyle = 'FixedDialog'
$form.MaximizeBox = $false
$form.Add_Shown({ $form.Activate(); $form.BringToFront() })
$intro = New-Object System.Windows.Forms.Label
$intro.Text = "设置本机 Wireshark 和 SSH 连接。密码认证无需私钥。`r`n受信任的工作台：$($settings.server)"
$intro.SetBounds(24, 18, 692, 55)
$form.Controls.Add($intro)
$table = New-Object System.Windows.Forms.TableLayoutPanel
$table.SetBounds(24, 84, 692, 294)
$table.ColumnCount = 3
$table.RowCount = 7
[void]$table.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 140)))
[void]$table.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Percent, 100)))
[void]$table.ColumnStyles.Add((New-Object System.Windows.Forms.ColumnStyle([System.Windows.Forms.SizeType]::Absolute, 80)))
$form.Controls.Add($table)
$fields = @{}
$definitions = @(@('wireshark','Wireshark 程序'), @('host','SSH 主机'), @('port','SSH 端口'), @('username','SSH 用户名'), @('profile','Profile（可留空）'), @('sshkey','私钥（密码登录留空）'), @('capture_dir','本机抓包保存目录'))
for ($index = 0; $index -lt $definitions.Count; $index++) {
  $key = $definitions[$index][0]
  [void]$table.RowStyles.Add((New-Object System.Windows.Forms.RowStyle([System.Windows.Forms.SizeType]::Absolute, 42)))
  $label = New-Object System.Windows.Forms.Label
  $label.Text = $definitions[$index][1]
  $label.Dock = 'Fill'
  $label.TextAlign = 'MiddleLeft'
  $inputBox = New-Object System.Windows.Forms.TextBox
  $inputBox.Text = [string]$settings.$key
  $inputBox.Anchor = 'Left,Right'
  $inputBox.Margin = New-Object System.Windows.Forms.Padding(4, 6, 8, 6)
  $fields[$key] = $inputBox
  $table.Controls.Add($label, 0, $index)
  $table.Controls.Add($inputBox, 1, $index)
  if ($key -in @('wireshark','sshkey','capture_dir')) {
    $browse = New-Object System.Windows.Forms.Button
    $browse.Text = '浏览…'
    $browse.Anchor = 'Left,Right'
    $browse.Height = 28
    $browse.Add_Click({
      if ($key -eq 'capture_dir') {
        $picker = New-Object System.Windows.Forms.FolderBrowserDialog
        $picker.SelectedPath = $inputBox.Text
        if ($picker.ShowDialog($form) -eq 'OK') { $inputBox.Text = $picker.SelectedPath }
      } else {
        $picker = New-Object System.Windows.Forms.OpenFileDialog
        if ($key -eq 'wireshark') { $picker.Filter = 'Wireshark|Wireshark.exe' }
        if ($picker.ShowDialog($form) -eq 'OK') { $inputBox.Text = $picker.FileName }
      }
      $picker.Dispose()
    }.GetNewClosure())
    $table.Controls.Add($browse, 2, $index)
  }
}
$automatic = New-Object System.Windows.Forms.CheckBox
$automatic.Text = '已有可用 Profile / 密钥认证，打开 Wireshark 后自动开始'
$automatic.Checked = [bool]$settings.autostart
$automatic.SetBounds(24, 390, 692, 28)
$form.Controls.Add($automatic)
$help = New-Object System.Windows.Forms.Label
$help.Text = "密码登录：不勾选上面的自动开始。在 Wireshark 首页点击 SSH remote capture`r`n旁的齿轮 → Authentication → 输入用户名、密码 → Start。无需配置私钥。`r`n每次抓包自动写入独立的 capture.pcapng；Web 会显示启动时指定的完整路径。`r`n密码只在本机 Wireshark 输入，本窗口不保存密码。"
$help.SetBounds(24, 429, 692, 78)
$form.Controls.Add($help)
$save = New-Object System.Windows.Forms.Button
$save.Text = '保存设置并继续'
$save.SetBounds(556, 519, 160, 34)
$save.Add_Click({
  if (-not (Test-Path -LiteralPath $fields.wireshark.Text -PathType Leaf) -or [IO.Path]::GetFileName($fields.wireshark.Text) -ine 'Wireshark.exe') {
    [void][System.Windows.Forms.MessageBox]::Show($form, '请选择图形程序 Wireshark.exe，不能选择 tshark.exe。', '检查程序路径'); return
  }
  if (-not $fields.username.Text.Trim()) {
    [void][System.Windows.Forms.MessageBox]::Show($form, '请填写 SSH 用户名；使用密码认证时私钥可以留空。', '检查连接'); return
  }
  $result = @{}
  foreach ($key in $fields.Keys) { $result[$key] = $fields[$key].Text }
  $result.autostart = $automatic.Checked
  $result | ConvertTo-Json | Set-Content -LiteralPath $OutputPath -Encoding UTF8
  $form.DialogResult = [System.Windows.Forms.DialogResult]::OK
  $form.Close()
})
$form.Controls.Add($save)
$form.AcceptButton = $save
[void]$form.ShowDialog()
$form.Dispose()
