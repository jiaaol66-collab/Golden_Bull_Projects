# 此文件是 start_notebook.exe.lnk 内嵌代码的可读源文件；快捷方式运行时不读取它。
$d=$pwd.Path
$b=$d
while($b-and!(Test-Path($b+'\base.txt'))){$p=Split-Path $b;if($p-eq$b){$b=$null}else{$b=$p}}
$y=$null
$j=$null
if($b){$m=gci $b -Directory -Filter myenv -Recurse -ea 0|?{Test-Path($_.FullName+'\Scripts\python.exe')}|select -f 1;if($m){$y=$m.FullName+'\Scripts\python.exe';$j=$m.FullName+'\Scripts\jupyter.exe';if(!(Test-Path $j)){$j=$null}}}
if(!$y){$j=(gcm jupyter -ea 0|select -f 1).Source;if(!$j){$y=(gcm python -ea 0|select -f 1).Source}}
# SN_TEST 仅供自动验证快捷方式使用，正常启动时不会设置。
if($env:SN_TEST){sc $env:SN_TEST @($d,$b,$y,$j);exit}
if(!$j-and!$y){write-host '没有可用的 Jupyter 或 Python。';pause;exit 1}
$i='否'
if(!$j){&$y -m notebook --version *>$null;if($LASTEXITCODE){$i='是';&$y -m pip install jupyter};if($LASTEXITCODE){write-host 'pip install jupyter 失败。';pause;exit 1}}
write-host('当前路径：'+$d)
write-host('Jupyter调用：'+$(if($j){$j}else{$y+' -m notebook'}))
write-host('本次pip安装：'+$i)
sl $d
if($j){&$j notebook}else{&$y -m notebook}
