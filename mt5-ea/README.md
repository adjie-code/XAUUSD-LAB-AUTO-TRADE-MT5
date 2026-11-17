# EA siap mount

`XAUUSDPattern/XAUUSDPatternExecutor.ex5` adalah EA gabungan lima strategi
yang sudah dikompilasi. File ini di-mount oleh `docker-compose.yml` ke:

```text
MQL5/Experts/XAUUSDPattern/XAUUSDPatternExecutor.ex5
```

Sumber EA ada di `../ea/XAUUSDPatternExecutor.mq5` dan memiliki
`InpAutoSymbol=true` agar broker dengan `XAUUSDc`, `XAUUSDb`, `XAUUSDm`, atau
`GOLD` tetap bisa dipilih otomatis.

Jika mengubah sumber EA, kompilasi ulang di MetaEditor (0 error, 0 warning),
lalu ganti file `.ex5` di folder ini.
