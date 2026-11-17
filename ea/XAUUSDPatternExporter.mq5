//+------------------------------------------------------------------+
//|                                        XAUUSDPatternExporter.mq5 |
//|  XAUUSD Pattern Dashboard - Fase 2 (integrasi data MT5)          |
//|                                                                  |
//|  Tugas: setiap candle M5 selesai, tulis ulang CSV berisi history  |
//|  candle M5 (OHLC) ke folder FILE_COMMON agar dibaca backend      |
//|  dashboard (Python). MODE Riset-saja: tidak ada transaksi.       |
//+------------------------------------------------------------------+
#property copyright "XAUUSD Pattern Dashboard"
#property version   "1.00"
#property description "Exporter candle M5 -> CSV (FILE_COMMON) untuk dashboard"

#property strict

//--- parameter
input int    InpMaxBars     = 5000;           // Jumlah candle M5 history yang diekspor
input int    InpTimerSec    = 10;             // Interval cek (detik)
input string InpOutFolder   = "XAUUSDPattern";// Subfolder di Exness Common/Files
input int    InpBackfillDays= 730;            // FASE 3: cakupan ekspor full history (hari)

datetime g_last_write = 0;   // waktu candle terakhir yang sudah diekspor
datetime g_last_full  = 0;   // waktu ekspor full-history terakhir

// Normalisasi zona waktu (11 Nov 2026): dashboard menyimpan candle ber-epoch
// UTC (kebiasaan server Exness GMT+0). Broker HFM memakai waktu server
// GMT+2/+3, sehingga candle baru bergeser +2 jam dari data lama dan engine
// salah cocok pola (similarity 99.99% = self-match). Kita normalkan ke GMT.
int ServerOffsetSec()
{
   return (int)(TimeCurrent() - TimeGMT());
}
long GmtTime(datetime server_time)
{
   return (long)server_time - ServerOffsetSec();
}

//+------------------------------------------------------------------+
int OnInit()
{
   EventSetTimer(MathMax(5, InpTimerSec));
   Print("XAUUSDPatternExporter aktif. Symbol=", Symbol(), ", TF=M5, MaxBars=", InpMaxBars);
   TryExport(true);  // ekspor pertama mungkin belum ada candle fresh, timer akan ulang
   TryBackfill();    // FASE 3: ekspor full history saat init
   return(INIT_SUCCEEDED);
}
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   EventKillTimer();
   Print("XAUUSDPatternExporter berhenti. reason=", reason);
}
//+------------------------------------------------------------------+
void OnTick()   { TryExport(false); TryBackfill(); }
void OnTimer()  { TryExport(false); }
//+------------------------------------------------------------------+
//| Ekspor hanya ketika ada candle M5 BARU yang selesai              |
//+------------------------------------------------------------------+
void TryExport(bool force)
{
   if(Bars(_Symbol, PERIOD_M5) < 10) return;

   datetime current_bar = iTime(_Symbol, PERIOD_M5, 0);   // candle yang berjalan
   if(!force && g_last_write != 0 && current_bar == g_last_write) return;

   // candle selesai = mulai dari posisi 1 (bukan 0 yang sedang berjalan)
   MqlRates rates[];
   ArraySetAsSeries(rates, false);             // index 0 = terlama
   int copied = CopyRates(_Symbol, PERIOD_M5, 1, InpMaxBars, rates);
   if(copied <= 0)
   {
      WriteHeartbeat("ERROR", copied, 0, 0);
      return;
   }

   int written = WriteCandlesCsv(rates, copied);
   if(written > 0)
   {
      g_last_write = current_bar;
      datetime last_close = rates[copied-1].time;
      WriteHeartbeat("OK", written, GmtTime(last_close), (long)TimeGMT());
   }
}

//+------------------------------------------------------------------+
//| FASE 3: Ekspor FULL history candle M5 -> candles_m5_full.csv     |
//| Dijalankan: saat init, lalu maksimal 1x per jam (hemat kerja).   |
//| Format baris identik dengan candles_m5.csv (delimiter ';').       |
//+------------------------------------------------------------------+
void TryBackfill()
{
   if(InpBackfillDays <= 0) return;                          // fitur dimatikan
   datetime now = TimeCurrent();
   if(g_last_full != 0 && now - g_last_full < 3600) return;  // maks 1x per jam
   g_last_full = now;

   datetime period_start = now - (datetime)InpBackfillDays * 86400;
   datetime period_end   = now;

   string tmp_name   = InpOutFolder + "/candles_m5_full.tmp";
   string final_name = InpOutFolder + "/candles_m5_full.csv";

   int h = FileOpen(tmp_name, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Print("Backfill: gagal buka tmp, err=", GetLastError());
      return;
   }

   int total = 0;
   // Salin per-blok 30 hari: aman terhadap batas server/terminal
   while(period_start < period_end)
   {
      datetime block_end = period_start + 30 * 86400;
      if(block_end > period_end) block_end = period_end;
      MqlRates rates[];
      int copied = CopyRates(_Symbol, PERIOD_M5, period_start, block_end, rates);
      if(copied > 0)
      {
         ArraySetAsSeries(rates, false);
         for(int i = 0; i < copied; i++)
         {
            if(rates[i].time + PeriodSeconds(PERIOD_M5) > now) continue; // candle berjalan belum selesai
            FileWrite(h,
                      GmtTime(rates[i].time),               // dinormalisasi ke GMT
                      DoubleToString(rates[i].open,  2),
                      DoubleToString(rates[i].high,  2),
                      DoubleToString(rates[i].low,   2),
                      DoubleToString(rates[i].close, 2),
                      (long)rates[i].tick_volume,
                      DoubleToString(rates[i].real_volume, 0),
                      (long)rates[i].spread);
            total++;
         }
      }
      else
      {
         Print("Backfill: CopyRates kosong rentang ", TimeToString(period_start),
               " err=", GetLastError());
      }
      period_start = block_end;
   }
   FileClose(h);

   if(total > 0)
   {
      if(FileMove(tmp_name, FILE_COMMON, final_name, FILE_REWRITE|FILE_COMMON))
         Print("Backfill SUKSES: ", total, " candle M5 full history -> ", final_name);
      else
         Print("Backfill: FileMove gagal, err=", GetLastError());
   }
   else
   {
      Print("Backfill: tidak ada data ", InpBackfillDays,
            " hari (server mungkin membatasi) - CSV rolling tetap dipakai");
   }
}

//+------------------------------------------------------------------+
//| Tulis CSV via file sementara lalu FileMove (atomic)              |
//+------------------------------------------------------------------+
int WriteCandlesCsv(const MqlRates &rates[], const int n)
{
   string tmp_name  = InpOutFolder + "/candles_m5.tmp";
   string final_name= InpOutFolder + "/candles_m5.csv";

   int h = FileOpen(tmp_name, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Print("Gagal buka file tmp, err=", GetLastError());
      return 0;
   }
   for(int i = 0; i < n; i++)
   {
      FileWrite(h,
                GmtTime(rates[i].time),              // unix epoch GMT awal candle (dinormalisasi dr server time)
                DoubleToString(rates[i].open,  2),
                DoubleToString(rates[i].high,  2),
                DoubleToString(rates[i].low,   2),
                DoubleToString(rates[i].close, 2),
                (long)rates[i].tick_volume,
                DoubleToString(rates[i].real_volume, 0),
                (long)rates[i].spread);
   }
   FileClose(h);

   if(!FileMove(tmp_name, FILE_COMMON, final_name, FILE_REWRITE|FILE_COMMON))
   {
      Print("Gagal FileMove, err=", GetLastError());
      return 0;
   }
   return n;
}
//+------------------------------------------------------------------+
//| Heartbeat: status terakhir exporter (diskriminan keungan data)   |
//+------------------------------------------------------------------+
void WriteHeartbeat(const string status, const long bars, const long last_close, const long synced)
{
   // FIX: FILE_TXT menempel field tanpa pemisah; FILE_CSV + ';' membuat
   // formatnya tetap "status;symbol;tf;bars;last_close;synced;write_time".
   string name = InpOutFolder + "/heartbeat.txt";
   int h = FileOpen(name, FILE_WRITE|FILE_CSV|FILE_ANSI|FILE_COMMON, ';');
   if(h == INVALID_HANDLE) return;
   FileWrite(h, status, Symbol(), "M5", bars, last_close, synced, (long)TimeCurrent());
   FileClose(h);
}
//+------------------------------------------------------------------+
