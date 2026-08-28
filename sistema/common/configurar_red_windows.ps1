param(
  [Parameter(Mandatory=$true)][string]$ProjectRoot,
  [Parameter(Mandatory=$true)][string]$PythonExe
)
$ErrorActionPreference = 'Stop'
$HostNameWanted = if($env:PULSIA_DNS_HOST){$env:PULSIA_DNS_HOST}else{'almacen'}
$ConfigureStatic = $env:PULSIA_CONFIGURE_STATIC_IP -eq '1'
$UpdateDns = $env:PULSIA_DNS_UPDATE -ne '0'
$AllowVmNat = $env:PULSIA_ALLOW_VM_NAT -eq '1'
$common = Join-Path $ProjectRoot 'sistema\common\network_dns.py'
$dataDir = Join-Path $ProjectRoot 'data'
New-Item -ItemType Directory -Path $dataDir -Force | Out-Null

function PrefixToMask([int]$prefix){
  if($prefix -lt 0 -or $prefix -gt 32){ throw "Prefijo CIDR IPv4 no válido: $prefix" }
  $remaining = $prefix
  $octets = foreach($i in 0..3){
    if($remaining -ge 8){ 255; $remaining -= 8 }
    elseif($remaining -gt 0){ [int](256 - [math]::Pow(2, 8 - $remaining)); $remaining = 0 }
    else { 0 }
  }
  return ($octets -join '.')
}
function Test-Tcp53([string]$ip){
  try {$c=[Net.Sockets.TcpClient]::new(); $a=$c.BeginConnect($ip,53,$null,$null); if(-not $a.AsyncWaitHandle.WaitOne(700)){ $c.Dispose(); return $false }; $c.EndConnect($a); $c.Dispose(); return $true} catch {return $false}
}

$route = Get-NetRoute -AddressFamily IPv4 -DestinationPrefix '0.0.0.0/0' -ErrorAction SilentlyContinue | Sort-Object RouteMetric,InterfaceMetric | Select-Object -First 1
if(-not $route){ Write-Warning 'No se encontró una ruta IPv4 por defecto. No se cambia la configuración de red.'; exit 0 }
$ifIndex = $route.InterfaceIndex
$adapter = Get-NetAdapter -InterfaceIndex $ifIndex -ErrorAction Stop
$ipObj = Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -AddressState Preferred -ErrorAction Stop | Where-Object {$_.IPAddress -notlike '169.254.*'} | Select-Object -First 1
if(-not $ipObj){ Write-Warning 'No se encontró una IPv4 LAN utilizable.'; exit 0 }
$ip = $ipObj.IPAddress; $prefix=[int]$ipObj.PrefixLength; $gateway=$route.NextHop
$dns = @((Get-DnsClientServerAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue).ServerAddresses | Where-Object {$_ -and $_ -notlike '127.*'})
$suffix = (Get-DnsClient -InterfaceIndex $ifIndex -ErrorAction SilentlyContinue).ConnectionSpecificSuffix
if(-not $suffix){ $suffix = (Get-DnsClientGlobalSetting -ErrorAction SilentlyContinue).SuffixSearchList | Select-Object -First 1 }

$cs = Get-CimInstance Win32_ComputerSystem -ErrorAction SilentlyContinue
$isVm = $false
$vmLabel = ''
if($cs){
  $vmLabel = (($cs.Manufacturer + ' ' + $cs.Model).Trim())
  $isVm = $vmLabel -match '(VirtualBox|VMware|Virtual Machine|KVM|QEMU|Xen|Parallels|Hyper-V)'
}
$probableVBoxNat = $isVm -and ($vmLabel -match 'VirtualBox|innotek|Oracle') -and $ip.StartsWith('10.0.2.') -and $gateway -eq '10.0.2.2'
if($isVm){ Write-Host "[INFO] Maquina virtual detectada: $vmLabel" -ForegroundColor Cyan }
if($probableVBoxNat){
  Write-Warning "Se detecta el patron de NAT por defecto de VirtualBox ($ip, gateway $gateway)."
  Write-Warning 'Para un servidor accesible desde la LAN use Adaptador puente en VirtualBox.'
  if(-not $AllowVmNat){
    Write-Host '[ERROR] La VM esta en NAT. Cambie VirtualBox a Adaptador puente y vuelva a ejecutar el instalador, o defina PULSIA_ALLOW_VM_NAT=1 solo si ha configurado port-forwarding conscientemente.' -ForegroundColor Red
    exit 20
  }
  $ConfigureStatic = $false
  $UpdateDns = $false
}

# En Windows 11/Server una NIC nueva de VM puede quedar como Public. Para una
# LAN RFC1918 la convertimos a Private, salvo que ya sea DomainAuthenticated.
try {
  $profile = Get-NetConnectionProfile -InterfaceIndex $ifIndex -ErrorAction Stop
  $privateIp = $ip -match '^(10\.|192\.168\.|172\.(1[6-9]|2[0-9]|3[01])\.)'
  if($privateIp -and $profile.NetworkCategory -eq 'Public'){
    Set-NetConnectionProfile -InterfaceIndex $ifIndex -NetworkCategory Private -ErrorAction Stop
    Write-Host '[OK] Perfil de red de la VM/servidor ajustado de Public a Private para la LAN privada.' -ForegroundColor Green
  }
} catch { Write-Warning "No se pudo revisar/cambiar el perfil de red: $($_.Exception.Message)" }

Write-Host "[INFO] Interfaz LAN: $($adapter.Name)" -ForegroundColor Cyan
Write-Host "[INFO] IPv4 actual : $ip/$prefix" -ForegroundColor Cyan
Write-Host "[INFO] Gateway     : $gateway" -ForegroundColor Cyan
Write-Host "[INFO] DNS         : $($dns -join ', ')" -ForegroundColor Cyan
if($suffix){Write-Host "[INFO] Zona/sufijo : $suffix" -ForegroundColor Cyan}

# Si Windows solo conoce un resolver local/stub o no anuncia DNS, buscar
# servidores DNS que respondan en la subred antes de desactivar DHCP.
if($dns.Count -eq 0){
  try {
    $json = & $PythonExe $common scan --cidr "$ip/$prefix"
    $obj = $json | ConvertFrom-Json
    $dns = @($obj.dns_servers)
    if($dns.Count -gt 0){Write-Host "[OK] DNS encontrado por escaneo: $($dns -join ', ')" -ForegroundColor Green}
  } catch { Write-Warning "No se pudo descubrir DNS por escaneo: $($_.Exception.Message)" }
}

$dhcp = (Get-NetIPInterface -InterfaceIndex $ifIndex -AddressFamily IPv4).Dhcp
if(-not $ConfigureStatic -and $dhcp -eq 'Enabled'){
  Write-Host '[OK] DHCP se conserva por defecto. Use la reserva DHCP por MAC/IP desde la app o defina PULSIA_CONFIGURE_STATIC_IP=1 para fijar localmente la IP actual.' -ForegroundColor Green
}
if($ConfigureStatic -and $dhcp -eq 'Enabled' -and $dns.Count -gt 0){
  $backup = [ordered]@{InterfaceAlias=$adapter.Name;InterfaceIndex=$ifIndex;IPAddress=$ip;PrefixLength=$prefix;Gateway=$gateway;Dns=$dns;WasDhcp=$true;Timestamp=(Get-Date).ToString('o')}
  $backup | ConvertTo-Json -Depth 4 | Set-Content -LiteralPath (Join-Path $dataDir 'network-backup-windows.json') -Encoding UTF8
  $mask=PrefixToMask $prefix
  Write-Host "[INFO] Fijando la IP DHCP actual como estática ($ip)..." -ForegroundColor Cyan
  & netsh interface ipv4 set address name="$($adapter.Name)" source=static address=$ip mask=$mask gateway=$gateway store=persistent | Out-Null
  if($dns.Count -gt 0){
    & netsh interface ipv4 set dnsservers name="$($adapter.Name)" source=static address=$($dns[0]) register=primary validate=no | Out-Null
    for($i=1;$i -lt $dns.Count;$i++){ & netsh interface ipv4 add dnsservers name="$($adapter.Name)" address=$($dns[$i]) index=($i+1) validate=no | Out-Null }
  }
  Start-Sleep -Seconds 2
  $now = Get-NetIPAddress -InterfaceIndex $ifIndex -AddressFamily IPv4 -ErrorAction SilentlyContinue | Where-Object {$_.IPAddress -eq $ip}
  if(-not $now){
    Write-Warning 'La IP estática no quedó aplicada; restaurando DHCP.'
    & netsh interface ipv4 set address name="$($adapter.Name)" source=dhcp | Out-Null
    & netsh interface ipv4 set dnsservers name="$($adapter.Name)" source=dhcp | Out-Null
  } else {
    Write-Host '[OK] IP actual fijada como estática sin cambiar de dirección.' -ForegroundColor Green
  }
} elseif($ConfigureStatic -and $dhcp -eq 'Enabled' -and $dns.Count -eq 0) {
  Write-Warning 'No se encontró un DNS real; por seguridad se conserva DHCP para no dejar el servidor sin resolución.'
} elseif($dhcp -ne 'Enabled') {
  Write-Host '[OK] La interfaz ya utiliza configuración IPv4 manual/estática.' -ForegroundColor Green
}

$dnsServer = if($env:PULSIA_DNS_SERVER){$env:PULSIA_DNS_SERVER}else{$dns | Where-Object {Test-Tcp53 $_} | Select-Object -First 1}
$zone = if($env:PULSIA_DNS_ZONE){$env:PULSIA_DNS_ZONE}else{$suffix}
$keyFile = if($env:PULSIA_DNS_TSIG_KEY_FILE){$env:PULSIA_DNS_TSIG_KEY_FILE}else{Join-Path $env:ProgramData 'PULSIA\Inventario\dns-update.key'}

if($UpdateDns -and $dnsServer -and $zone){
  $fqdn="$HostNameWanted.$zone"
  Write-Host "[INFO] DNS corporativo candidato: $dnsServer; registro: $fqdn -> $ip" -ForegroundColor Cyan
  if(Test-Path -LiteralPath $keyFile){
    try {
      & $PythonExe $common update --server $dnsServer --zone $zone --host $HostNameWanted --address $ip --key-file $keyFile | Out-Null
      Start-Sleep -Milliseconds 600
      $answer=(Resolve-DnsName -Name $fqdn -Type A -Server $dnsServer -ErrorAction Stop | Where-Object IPAddress | Select-Object -First 1 -ExpandProperty IPAddress)
      if($answer -eq $ip){Write-Host "[OK] DNS actualizado y verificado: $fqdn -> $ip" -ForegroundColor Green}else{Write-Warning "El DNS respondió $answer después de la actualización."}
    } catch { Write-Warning "No se pudo actualizar el DNS por RFC2136/TSIG: $($_.Exception.Message)" }
  } else {
    Write-Warning "DNS detectado, pero no existe clave TSIG autorizada en $keyFile. No se intentan actualizaciones DNS anónimas."
    @("DNS_SERVER=$dnsServer","DNS_ZONE=$zone","DNS_HOST=$HostNameWanted","DNS_IP=$ip") | Set-Content -LiteralPath (Join-Path $dataDir 'dns-registro-pendiente.txt') -Encoding ASCII
  }
} elseif($UpdateDns){
  Write-Warning 'No se pudo determinar simultáneamente servidor DNS y zona. Se mantiene el paquete cliente/hosts como fallback.'
}
