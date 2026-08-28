[CmdletBinding()]
param([string]$ServerIp)
$ErrorActionPreference='Stop'
$ScriptDir=Split-Path -Parent $MyInvocation.MyCommand.Path
$CertFile=Join-Path $ScriptDir 'PULSIA-Inventario-Root-CA.crt'
$ConfigFile=Join-Path $ScriptDir 'servidor_cliente.ini'
$AppHost='almacen';$AppUrl='https://almacen'
$LogDir=Join-Path $env:ProgramData 'PULSIA\Inventario\logs';New-Item -ItemType Directory -Force $LogDir -ErrorAction SilentlyContinue|Out-Null;if(-not(Test-Path $LogDir)){$LogDir=$env:TEMP}
$Log=Join-Path $LogDir 'PULSIA-Cliente-Windows.log'
function L($level,$msg){$line='{0} [{1}] {2}' -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss.fff'),$level,$msg;Write-Host $line;Add-Content -LiteralPath $Log -Value $line -Encoding UTF8 -ErrorAction SilentlyContinue}
function Admin(){([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)}
function Resolve-AlmacenIp(){try{$r=Resolve-DnsName -Name $AppHost -Type A -ErrorAction SilentlyContinue|Select-Object -First 1 -ExpandProperty IPAddress;if($r){return $r}}catch{};try{return ([Net.Dns]::GetHostAddresses($AppHost)|Where-Object AddressFamily -eq InterNetwork|Select-Object -First 1).IPAddressToString}catch{};return $null}
function Ensure-Hosts($ip){$hosts=Join-Path $env:SystemRoot 'System32\drivers\etc\hosts';$c=@(Get-Content $hosts -ErrorAction Stop)|Where-Object{$_ -notmatch '^\s*[^#\s]+\s+almacen(?:\s|$)'};$c += "$ip almacen # PULSIA Inventario";$tmp="$hosts.pulsia.tmp";Set-Content $tmp $c -Encoding ASCII;Move-Item $tmp $hosts -Force;ipconfig /flushdns|Out-Null}
L INFO "Inicio cliente Windows. Script=$($MyInvocation.MyCommand.Path)"
if(-not(Admin)){$args='-NoProfile -ExecutionPolicy Bypass -File "'+$MyInvocation.MyCommand.Path+'"'+$(if($ServerIp){' -ServerIp "'+$ServerIp+'"'}else{''});try{$p=Start-Process powershell.exe -ArgumentList $args -Verb RunAs -Wait -PassThru;exit $p.ExitCode}catch{L ERROR $_.Exception.Message;exit 5}}
try{
 if(-not(Test-Path $CertFile)){throw "Falta certificado $CertFile. Use el paquete generado por el servidor."}
 $cfg=@{};if(Test-Path $ConfigFile){foreach($ln in Get-Content $ConfigFile){if($ln -match '^([^=]+)=(.*)$'){$cfg[$matches[1]]=$matches[2]}}}
 if(-not$ServerIp -and $cfg.SERVER_IP){$ServerIp=$cfg.SERVER_IP}
 if($cfg.CA_SHA256){$actual=(Get-FileHash $CertFile -Algorithm SHA256).Hash;if($actual -ne $cfg.CA_SHA256){throw "Huella CA incorrecta. Esperada=$($cfg.CA_SHA256), actual=$actual"};L OK 'Huella SHA256 de CA verificada.'}
 if(-not$ServerIp){$ServerIp=Resolve-AlmacenIp}
 if(-not$ServerIp){$ServerIp=Read-Host 'Introduzca la IP LAN del servidor PULSIA'}
 $parsed=$null;if((-not [Net.IPAddress]::TryParse($ServerIp,[ref]$parsed)) -or $parsed.AddressFamily -ne [Net.Sockets.AddressFamily]::InterNetwork){throw "IP invalida: $ServerIp"}
 L INFO "Servidor esperado: $ServerIp"
 $resolved=Resolve-AlmacenIp;if($resolved -ne $ServerIp){L INFO 'DNS no apunta al servidor esperado; creando fallback hosts.';Ensure-Hosts $ServerIp}
 & certutil.exe -addstore -f Root $CertFile | ForEach-Object{if($_){L CERT $_}};if($LASTEXITCODE -ne 0){throw 'certutil no pudo instalar la CA.'}
 $thumb=([Security.Cryptography.X509Certificates.X509Certificate2]::new($CertFile)).Thumbprint;if(-not(Test-Path "Cert:\LocalMachine\Root\$thumb")){throw 'La CA no aparece en LocalMachine\Root.'}
 $ff=(Test-Path "$env:ProgramFiles\Mozilla Firefox") -or (Test-Path "${env:ProgramFiles(x86)}\Mozilla Firefox");if($ff){$p='HKLM:\SOFTWARE\Policies\Mozilla\Firefox\Certificates';New-Item $p -Force|Out-Null;New-ItemProperty $p -Name ImportEnterpriseRoots -PropertyType DWord -Value 1 -Force|Out-Null}
 ipconfig /flushdns|Out-Null
 $tcp=Test-NetConnection -ComputerName $AppHost -Port 443 -WarningAction SilentlyContinue;if(-not$tcp.TcpTestSucceeded){throw 'TCP/443 no es accesible.'};if(-not$tcp.RemoteAddress -or $tcp.RemoteAddress.IPAddressToString -ne $ServerIp){throw "almacen resuelve a $($tcp.RemoteAddress) y se esperaba $ServerIp"}
 try{$r=Invoke-WebRequest -UseBasicParsing -Uri "$AppUrl/" -TimeoutSec 15;if($r.StatusCode -lt 200 -or $r.StatusCode -ge 500){throw "HTTP $($r.StatusCode)"}}catch{throw "HTTPS no valida: $($_.Exception.Message)"}
 L OK "Cliente configurado. $AppUrl";Start-Process $AppUrl;exit 0
}catch{L ERROR $_.Exception.Message;exit 1}
