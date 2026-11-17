//+------------------------------------------------------------------+
//| XAUUSDPatternExecutor.mq5                                        |
//| EA GABUNGAN: exporter M5 + 5 strategi order.                     |
//| DEMO ONLY.                                                       |
//|                                                                  |
//| Sejak 16 Nov 2026 EA ini menjadi SATU file untuk lima strategi:   |
//|   1) PATTERN      : membaca sinyal pattern dari signal.txt       |
//|   2) PULLBACK     : tren H1 + pullback M5                        |
//|   3) MEANREV      : RSI/Bollinger M5 + filter H1                 |
//|   4) BREAKOUT     : breakout range Asia -> London                |
//|   5) CONFLUENCE   : sinyal PATTERN yang searah forecast model    |
//|                                                                  |
//| Tujuan: cukup satu file .mq5 untuk di-compile dan dijalankan.     |
//| Tidak ada file .mqh tambahan; hanya <Trade\Trade.mqh> standar.    |
//|                                                                  |
//| Identitas posisi:                                                |
//|   PATTERN    -> magic 20261111, komentar "PAT-<id>"              |
//|   PULLBACK   -> magic 20261113 (default), komentar "PB-<id>"     |
//|   MEANREV    -> magic 20261114, komentar "MR-<id>"               |
//|   BREAKOUT   -> magic 20261115, komentar "BO-<id>"               |
//|   CONFLUENCE -> magic 20261116, komentar "CF-<id>"               |
//| Magic adalah sumber kebenaran; komentar hanya untuk tampilan.    |
//|                                                                  |
//| Komunikasi (folder Common/Files):                                |
//|   baca  signal.txt    : sinyal pattern dari server dashboard     |
//|   tulis exec_log.txt  : hasil eksekusi semua strategi            |
//|   tulis exec_state.txt: id sinyal yang sudah diproses            |
//|   tulis candles_m5.csv + heartbeat.txt: data dashboard           |
//|   tulis inst_<chart>.txt: heartbeat instance (anti EA ganda)     |
//|                                                                  |
//| Pengaman wajib:                                                  |
//|   - akun WAJIB DEMO (ACCOUNT_TRADE_MODE_DEMO); real ditolak.      |
//|   - total posisi dibatasi input global (default 20).             |
//|   - PATTERN dibatasi 3 slot; PULLBACK tetap 2 slot.              |
//|   - total entry per candle dibatasi (default 20).                |
//|   - satu sinyal hanya dieksekusi sekali (tahan restart).         |
//|   - sinyal pattern lebih tua dari 12 menit ditolak.              |
//|   - hanya instance PRIMER (ChartID terkecil) yang trading/ekspor.|
//+------------------------------------------------------------------+
#property copyright "XAUUSD Pattern Dashboard"
#property version   "2.00"
#property description "Gabungan exporter + pattern executor + pullback tren (DEMO ONLY)"

#include <Trade\Trade.mqh>

// Symbol yang diperdagangkan — samakan dengan auto_trade.symbol di config.
// Akun demo HFM: XAUUSD (standar). Akun cent Exness: XAUUSDc.
input string SYMBOL_TRADE = "XAUUSD";
input bool   InpAutoSymbol = true;  // cari otomatis XAUUSD/GOLD yang tersedia di broker

// --- Ekspor candle M5 (digabung dari XAUUSDPatternExporter) ---
input int    InpMaxBars    = 5000;             // candle M5 history yang diekspor
input string InpOutFolder  = "XAUUSDPattern";  // subfolder Common/Files

// --- Strategi PATTERN (signal.txt) ---
input bool   InpPatternEnabled = true;        // aktifkan eksekusi sinyal pattern
input int    InpPatternMaxPositions = 3;      // slot maksimal untuk PATTERN
input bool   InpPatternLiveTrendGuard = true; // tolak PATTERN bila candle live melawan EMA13
input int    InpPatternTrendPeriod = 13;      // periode EMA tren live khusus PATTERN
input bool   InpPatternAutoExit = true;       // exit otomatis PATTERN (time stop / tren berbalik)
input int    InpPatternMaxHoldMinutes = 240; // time stop PATTERN (menit); 0 = nonaktif
input bool   InpPatternExitOnTrendReversal = true; // exit bila H1 + M5 live berbalik melawan
input double InpPatternMinRR = 1.00;          // RR minimum aktual PATTERN (TP >= SL)
input bool   InpPatternExitOnBadRR = true;    // exit PATTERN bila RR aktual < minimum

// --- Batas risiko global (berlaku untuk kedua strategi) ---
// Tidak ada filter lawan arah antar strategi: entry PULLBACK tidak melihat
// posisi PATTERN, dan sebaliknya. Masing-masing hanya dibatasi slot sendiri
// (3 PATTERN + 2 PULLBACK) serta batas risiko akun di bawah ini.
input int    InpGlobalMaxPositions20 = 20;      // total posisi XAUUSD maksimal (slot 3+2+5+5+5)
input int    InpMaxOrdersPerCandle20 = 5;       // entry maksimal per candle M5 (dibatasi 5)

// --- Strategi PULLBACK TREN (dihitung mandiri di EA) ---
input bool   InpPullbackEnabled = true;       // aktifkan strategi pullback
input bool   InpPullbackShadowOnly = false;   // true = catat sinyal saja, tanpa order
input int    InpPullbackMagic = 20261113;     // magic khusus posisi pullback
input double InpPullbackLot = 0.01;           // lot tetap pullback
input int    InpPullbackMaxPositions = 2;     // slot maksimal untuk PULLBACK
input int    InpPullbackMaxEntriesPerDay = 2; // batas entry pullback per hari (0 = bebas)
input int    InpTrendFastEMA = 50;            // EMA cepat tren H1
input int    InpTrendSlowEMA = 200;           // EMA lambat tren H1
input int    InpPullbackEMA = 20;             // EMA pullback di M5
input int    InpATRPeriod = 14;               // ATR M5
input double InpPullbackTolATR = 0.15;        // toleransi sentuh EMA (x ATR)
input double InpPullbackMaxExtATR = 1.50;     // maksimum jarak close dari EMA (x ATR)
input double InpSLBufferATR = 0.40;           // buffer SL di balik swing (x ATR)
input double InpMaxSLATR = 2.50;              // SL maksimal (x ATR); lebih dari ini dilewati
input double InpRR = 1.50;                    // target R:R pullback
input bool   InpUseTrailing = true;           // trailing stop setelah 1R
input double InpTrailStartR = 1.00;           // mulai trailing setelah profit 1R
input double InpTrailATRMult = 1.00;          // jarak trailing dari harga (x ATR)
input int    InpMaxHoldMinutes = 240;         // time stop (menit); 0 = nonaktif
input int    InpMaxSpreadPoints = 120;        // spread maksimal (poin); 0 = nonaktif
input bool   InpUseSessionFilter = true;      // batasi entry pullback per sesi
input int    InpSessionStartUTC = 7;          // jam mulai sesi (GMT/UTC)
input int    InpSessionEndUTC = 21;           // jam selesai sesi (GMT/UTC)

// --- MEAN REVERSION H1 (M5 RSI/Bollinger + filter H1) ---
input bool   InpMeanRevEnabled = true;        // aktifkan MEANREV
input int    InpMeanRevMagic = 20261114;      // magic MEANREV
input double InpMeanRevLot = 0.01;            // lot tetap MEANREV
input int    InpMeanRevMaxPositions = 5;      // slot MEANREV
input double InpMeanRevSLATR = 1.50;          // SL MEANREV (x ATR)
input double InpMeanRevTPATR = 2.00;          // TP MEANREV (x ATR)
input int    InpMeanRevHoldBars = 10;         // time stop MEANREV (bar M5)
input bool   InpMeanRevShadowOnly = false;    // true = catat sinyal tanpa order

// --- SESSION BREAKOUT (range Asia -> London) ---
input bool   InpBreakoutEnabled = true;       // aktifkan BREAKOUT
input int    InpBreakoutMagic = 20261115;     // magic BREAKOUT
input double InpBreakoutLot = 0.01;           // lot tetap BREAKOUT
input int    InpBreakoutMaxPositions = 5;     // slot BREAKOUT
input int    InpBreakoutMaxEntriesPerDay = 1; // maksimal entry BREAKOUT per hari
input int    InpBreakoutRangeStartUTC = 0;    // awal range Asia (jam UTC)
input int    InpBreakoutRangeEndUTC = 7;      // akhir range Asia (jam UTC)
input int    InpBreakoutEntryEndUTC = 12;     // akhir jendela entry (jam UTC)
input double InpBreakoutSLATR = 1.50;         // SL BREAKOUT (x ATR)
input double InpBreakoutTPATR = 2.00;         // TP BREAKOUT (x ATR)
input int    InpBreakoutHoldBars = 12;        // time stop BREAKOUT (bar M5)
input bool   InpBreakoutShadowOnly = false;   // true = catat sinyal tanpa order

// --- CONFLUENCE: sinyal PATTERN + forecast arah ---
input bool   InpConfluenceEnabled = true;     // aktifkan CONFLUENCE
input int    InpConfluenceMagic = 20261116;   // magic CONFLUENCE
input double InpConfluenceLot = 0.01;         // lot tetap CONFLUENCE
input int    InpConfluenceMaxPositions = 5;   // slot CONFLUENCE
input int    InpConfluenceMaxHoldMinutes = 240; // time stop CONFLUENCE (menit)
input bool   InpConfluenceRequireHigh = false;  // hanya forecast high-confidence
input bool   InpConfluenceShadowOnly = false;   // true = catat sinyal tanpa order

// --- Filter spread strategi baru ---
input int    InpNewMaxSpreadPoints = 120;     // spread maksimal MEANREV/BREAKOUT/CONFLUENCE
input bool   InpAuditNewStrategies = true;    // exit otomatis bila tesis strategi baru tidak valid
input int    InpMarginBufferPct = 20;         // sisa free margin minimum setelah entry (%)

#define MAGIC_PATTERN   20261111               // magic lama PATTERN (jangan diubah)
#define MAX_SIGNAL_AGE_SEC (12 * 60)           // sinyal pattern lebih tua = basi
#define SIGNAL_FILE     "signal.txt"
#define EXECLOG_FILE    "exec_log.txt"
#define STATE_FILE      "exec_state.txt"
#define POSITIONS_FILE  "positions.txt"
#define PNL_FILE        "pnl.txt"
#define EA_SUBFOLDER    "XAUUSDPattern"
#define INSTANCE_PREFIX "inst_"
#define PRIMARY_FRESH_SEC 15

CTrade  trade;

string  g_symbol = "";                // symbol yang dipakai (fallback chart)
long    g_pb_magic = 0;               // magic pullback aktif
long    g_mr_magic = 0;               // magic mean reversion
long    g_bo_magic = 0;               // magic breakout
long    g_cf_magic = 0;               // magic confluence
bool    g_pullback_ready = false;     // handle indikator pullback siap?
bool    g_new_ready = false;          // handle indikator strategi baru siap?

int     g_h_ema_fast = INVALID_HANDLE; // EMA cepat H1
int     g_h_ema_slow = INVALID_HANDLE; // EMA lambat H1
int     g_h_pull_ema = INVALID_HANDLE; // EMA pullback M5
int     g_h_atr      = INVALID_HANDLE; // ATR M5
int     g_h_pattern_ema = INVALID_HANDLE; // EMA13 live khusus PATTERN
int     g_h_rsi = INVALID_HANDLE;     // RSI14 M5 untuk strategi baru
int     g_h_bb = INVALID_HANDLE;      // Bollinger20 M5 untuk strategi baru
int     g_h_m5_ema200 = INVALID_HANDLE; // EMA200 M5 untuk forecast

string  g_last_done_id = "";          // id sinyal terakhir yang sudah diproses
string  g_last_refuse  = "";          // anti spam log penolakan berulang
int     g_header_maxpos = 5;          // maxpos dari header signal.txt
int     g_header_probmin = 75;        // prob_min dari header signal.txt
int     g_header_anchor_t = 0;        // anchor_t (epoch) dari header signal.txt
string  g_done_ids[];                 // semua id sinyal yang sudah dieksekusi
string  g_refused[];                  // penolakan yang sudah dicatat (anti spam)

datetime g_last_write = 0;            // candle M5 terakhir yang diekspor
bool     g_is_primary = true;         // instance ini pemegang peran trading/ekspor?
bool     g_role_known = false;        // sudah pernah log peran?
string   g_instance_file = "";        // file heartbeat instance ini

datetime g_last_pb_bar = 0;           // bar M5 terakhir yang dievaluasi pullback
datetime g_last_mr_bar = 0;           // bar M5 terakhir yang dievaluasi MEANREV
datetime g_last_bo_bar = 0;           // bar M5 terakhir yang dievaluasi BREAKOUT
datetime g_last_pnl_write = 0;        // throttle snapshot P/L harian
datetime g_order_candle = 0;          // candle M5 untuk hitungan entry global
int      g_order_count = 0;           // jumlah entry sukses di candle tersebut

//+------------------------------------------------------------------+
//| Util umum                                                       |
//+------------------------------------------------------------------+
bool IsOurMagic(long magic)
{
   return (magic == (long)MAGIC_PATTERN || magic == g_pb_magic ||
           magic == g_mr_magic || magic == g_bo_magic ||
           magic == g_cf_magic);
}

string StrategyLabel(long magic)
{
   if(magic == (long)MAGIC_PATTERN)
      return "PATTERN";
   if(magic == g_pb_magic)
      return "PULLBACK";
   if(magic == g_mr_magic)
      return "MEANREV";
   if(magic == g_bo_magic)
      return "BREAKOUT";
   if(magic == g_cf_magic)
      return "CONFLUENCE";
   return "LAIN";
}

bool IsDemoAccountSafe()
{
   return (AccountInfoInteger(ACCOUNT_TRADE_MODE) == ACCOUNT_TRADE_MODE_DEMO);
}

string AccountModeName()
{
   long m = AccountInfoInteger(ACCOUNT_TRADE_MODE);
   if(m == ACCOUNT_TRADE_MODE_DEMO)    return "DEMO";
   if(m == ACCOUNT_TRADE_MODE_CONTEST) return "CONTEST";
   return "REAL";
}

bool IsNettingAccount()
{
   return (AccountInfoInteger(ACCOUNT_MARGIN_MODE) ==
           ACCOUNT_MARGIN_MODE_RETAIL_NETTING);
}

int TimeUTC()
{
   return (int)TimeGMT();
}

//+------------------------------------------------------------------+
//| State id sinyal — tahan restart EA/terminal                      |
//+------------------------------------------------------------------+
bool IsNewSignal(string id)
{
   for(int i = 0; i < ArraySize(g_done_ids); i++)
      if(g_done_ids[i] == id)
         return false;
   return true;
}

void MarkDone(string id)
{
   int n = ArraySize(g_done_ids);
   ArrayResize(g_done_ids, n + 1);
   g_done_ids[n] = id;
   g_last_done_id = id;
}

void SaveState(string id)
{
   int h = FileOpen(EA_SUBFOLDER + "\\" + STATE_FILE,
                    FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI |
                    FILE_COMMON | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return;
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, id + "\r\n");
   FileClose(h);
}

void LoadState()
{
   int h = FileOpen(EA_SUBFOLDER + "\\" + STATE_FILE,
                    FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON |
                    FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return;
   while(!FileIsEnding(h))
   {
      string id = FileReadString(h);
      if(StringLen(id) > 0)
         MarkDone(id);
   }
   FileClose(h);
}

//+------------------------------------------------------------------+
//| Log hasil eksekusi — tetap kompatibel dengan parser dashboard    |
//| Format: EXEC;epoch;id;side;retcode;ticket;hasil;[strategi] note   |
//+------------------------------------------------------------------+
void WritePositionsSnapshot()
{
   string tmp_name = InpOutFolder + "/positions.tmp";
   string final_name = InpOutFolder + "/" + POSITIONS_FILE;
   int h = FileOpen(tmp_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      long magic = (long)PositionGetInteger(POSITION_MAGIC);
      if(!IsOurMagic(magic))
         continue;
      long type = PositionGetInteger(POSITION_TYPE);
      string side = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      string line = "POS;" + IntegerToString(magic) + ";" +
                    StrategyLabel(magic) + ";" +
                    IntegerToString((long)ticket) + ";" + side + ";" +
                    DoubleToString(PositionGetDouble(POSITION_VOLUME), 2) + ";" +
                    DoubleToString(PositionGetDouble(POSITION_PRICE_OPEN), 2) + ";" +
                    DoubleToString(PositionGetDouble(POSITION_SL), 2) + ";" +
                    DoubleToString(PositionGetDouble(POSITION_TP), 2) + ";" +
                    DoubleToString(PositionGetDouble(POSITION_PRICE_CURRENT), 2) + ";" +
                    DoubleToString(PositionGetDouble(POSITION_PROFIT), 2) + ";" +
                    IntegerToString((long)PositionGetInteger(POSITION_TIME) -
                                   ((long)TimeCurrent() - (long)TimeGMT())) + "\r\n";
      FileWriteString(h, line);
   }
   FileClose(h);
   FileMove(tmp_name, FILE_COMMON, final_name, FILE_REWRITE | FILE_COMMON);
}

void WritePnlSnapshot()
{
   datetime now = TimeCurrent();
   if(g_last_pnl_write != 0 && now - g_last_pnl_write < 60)
      return;
   g_last_pnl_write = now;

   datetime from = now - 180 * 86400;
   if(!HistorySelect(from, now))
      return;

   string dates[];
   long magics[];
   int trades[];
   double pnls[];
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      long magic = (long)HistoryDealGetInteger(ticket, DEAL_MAGIC);
      if(!IsOurMagic(magic))
         continue;
      long entry = (long)HistoryDealGetInteger(ticket, DEAL_ENTRY);
      if(entry != DEAL_ENTRY_OUT && entry != DEAL_ENTRY_OUT_BY &&
         entry != DEAL_ENTRY_INOUT)
         continue;
      datetime dt = (datetime)HistoryDealGetInteger(ticket, DEAL_TIME);
      MqlDateTime st;
      TimeToStruct(dt, st);
      string day = StringFormat("%04d-%02d-%02d", st.year, st.mon, st.day);
      double pnl = HistoryDealGetDouble(ticket, DEAL_PROFIT) +
                   HistoryDealGetDouble(ticket, DEAL_SWAP) +
                   HistoryDealGetDouble(ticket, DEAL_COMMISSION);
      int found = -1;
      for(int j = 0; j < ArraySize(dates); j++)
      {
         if(dates[j] == day && magics[j] == magic)
         {
            found = j;
            break;
         }
      }
      if(found < 0)
      {
         int n = ArraySize(dates);
         ArrayResize(dates, n + 1);
         ArrayResize(magics, n + 1);
         ArrayResize(trades, n + 1);
         ArrayResize(pnls, n + 1);
         dates[n] = day;
         magics[n] = magic;
         trades[n] = 0;
         pnls[n] = 0.0;
         found = n;
      }
      trades[found] += 1;
      pnls[found] += pnl;
   }

   string tmp_name = InpOutFolder + "/pnl.tmp";
   string final_name = InpOutFolder + "/" + PNL_FILE;
   int h = FileOpen(tmp_name, FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h == INVALID_HANDLE)
      return;
   MqlDateTime nd;
   TimeToStruct(now, nd);
   FileWriteString(h, StringFormat("META;%04d-%02d-%02d\r\n",
                    nd.year, nd.mon, nd.day));
   for(int i = 0; i < ArraySize(dates); i++)
   {
      string line = "PNL;" + dates[i] + ";" + IntegerToString(magics[i]) + ";" +
                    StrategyLabel(magics[i]) + ";" +
                    IntegerToString(trades[i]) + ";" +
                    DoubleToString(pnls[i], 2) + "\r\n";
      FileWriteString(h, line);
   }
   FileClose(h);
   FileMove(tmp_name, FILE_COMMON, final_name, FILE_REWRITE | FILE_COMMON);
}

void LogExec(string strategy, string id, string side, long retcode,
             long ticket, string result, string note)
{
   int h = FileOpen(EA_SUBFOLDER + "\\" + EXECLOG_FILE,
                    FILE_READ | FILE_WRITE | FILE_TXT | FILE_ANSI |
                    FILE_COMMON | FILE_SHARE_READ);
   if(h == INVALID_HANDLE)
      return;
   FileSeek(h, 0, SEEK_END);
   FileWriteString(h, StringFormat("EXEC;%d;%s;%s;%d;%s;%s;[%s] %s\r\n",
                    (int)TimeUTC(), id, side, (int)retcode, IntegerToString(ticket),
                    result, strategy, note));
   FileClose(h);
}

void RefuseOnce(string reason)
{
   if(g_last_refuse == reason)
      return;
   g_last_refuse = reason;
   LogExec("GLOBAL", "-", "-", 0, 0, "refuse", reason);
}

void Refuse(string strategy, string id, string side, string reason)
{
   string key = strategy + "|" + id + "|" + reason;
   for(int i = 0; i < ArraySize(g_refused); i++)
      if(g_refused[i] == key)
         return;
   int n = ArraySize(g_refused);
   if(n >= 24)
   {
      for(int j = 1; j < n; j++)
         g_refused[j - 1] = g_refused[j];
      ArrayResize(g_refused, n - 1);
      n--;
   }
   ArrayResize(g_refused, n + 1);
   g_refused[n] = key;
   LogExec(strategy, id, side, 0, 0, "refuse", reason);
}

//+------------------------------------------------------------------+
//| Batas posisi / entry                                             |
//+------------------------------------------------------------------+
int CountPositionsByMagic(long magic)
{
   int cnt = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) == g_symbol &&
         PositionGetInteger(POSITION_MAGIC) == magic)
         cnt++;
   }
   return cnt;
}

int CountAllEAOpenPositions()
{
   int cnt = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if(IsOurMagic((long)PositionGetInteger(POSITION_MAGIC)))
         cnt++;
   }
   return cnt;
}

int CountEntriesThisCandle()
{
   datetime candle = iTime(g_symbol, PERIOD_M5, 0);
   if(candle == 0)
      return 0;

   int cnt = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if(!IsOurMagic((long)PositionGetInteger(POSITION_MAGIC)))
         continue;
      datetime open_t = (datetime)PositionGetInteger(POSITION_TIME);
      if(open_t >= candle)
         cnt++;
   }
   return cnt;
}

bool CanOpenGlobal()
{
   datetime candle = iTime(g_symbol, PERIOD_M5, 0);
   int cnt = CountEntriesThisCandle();
   if(candle != 0 && g_order_candle == candle)
      cnt = (int)MathMax((double)cnt, (double)g_order_count);
   int cap = (int)MathMin(5, MathMax(1, InpMaxOrdersPerCandle20));
   return (cnt < cap);
}

void RegisterOrder()
{
   datetime candle = iTime(g_symbol, PERIOD_M5, 0);
   if(candle != g_order_candle)
   {
      g_order_candle = candle;
      g_order_count = 0;
   }
   g_order_count++;
}

int PatternMaxPositions()
{
   int mp = (g_header_maxpos > 0) ? g_header_maxpos : 5;
   mp = (int)MathMin((double)mp, (double)InpPatternMaxPositions);
   mp = (int)MathMin((double)mp, (double)InpGlobalMaxPositions20);
   return (int)MathMax(1.0, (double)mp);
}

int GlobalMaxPositions()
{
   return (int)MathMax(1, InpGlobalMaxPositions20);
}

//+------------------------------------------------------------------+
//| Bantu perhitungan pullback                                       |
//+------------------------------------------------------------------+
bool GetBufferValue(int handle, int shift, double &value)
{
   if(handle == INVALID_HANDLE)
      return false;
   double buf[];
   if(CopyBuffer(handle, 0, shift, 1, buf) != 1)
      return false;
   value = buf[0];
   return true;
}

int H1Trend()
{
   if(g_h_ema_fast == INVALID_HANDLE || g_h_ema_slow == INVALID_HANDLE)
      return 0;
   if(Bars(g_symbol, PERIOD_H1) < MathMax(InpTrendFastEMA, InpTrendSlowEMA) + 2)
      return 0;

   double fast = 0.0, slow = 0.0;
   if(!GetBufferValue(g_h_ema_fast, 1, fast) ||
      !GetBufferValue(g_h_ema_slow, 1, slow))
      return 0;

   double h1_close = iClose(g_symbol, PERIOD_H1, 1);
   if(h1_close <= 0.0 || fast <= 0.0 || slow <= 0.0)
      return 0;

   if(fast > slow && h1_close > fast)
      return 1;                              // tren H1 NAIK
   if(fast < slow && h1_close < fast)
      return -1;                             // tren H1 TURUN
   return 0;                                 // sideways / belum jelas
}

bool SessionOK()
{
   if(!InpUseSessionFilter)
      return true;

   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   int h = dt.hour;
   int start = (int)MathMax(0, MathMin(23, InpSessionStartUTC));
   int end   = (int)MathMax(0, MathMin(23, InpSessionEndUTC));
   if(start == end)
      return true;
   if(start < end)
      return (h >= start && h < end);
   return (h >= start || h < end);           // sesi melewati tengah malam
}

bool SpreadTooWide()
{
   if(InpMaxSpreadPoints <= 0)
      return false;
   long spread = SymbolInfoInteger(g_symbol, SYMBOL_SPREAD);
   return (spread > (long)InpMaxSpreadPoints);
}

double MinStopDistance()
{
   double point = SymbolInfoDouble(g_symbol, SYMBOL_POINT);
   if(point <= 0.0)
      point = 0.01;
   long stops = SymbolInfoInteger(g_symbol, SYMBOL_TRADE_STOPS_LEVEL);
   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   double spread = MathMax(ask - bid, point);
   return (double)stops * point + spread + 2.0 * point;
}

double NormalizeLot(double lot)
{
   double step = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_STEP);
   double minv = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MIN);
   double maxv = SymbolInfoDouble(g_symbol, SYMBOL_VOLUME_MAX);
   if(step <= 0.0)
      step = 0.01;
   if(maxv <= 0.0)
      maxv = 10.0;
   double v = MathFloor(lot / step) * step;
   if(v < minv)
      v = minv;
   if(v > maxv)
      v = maxv;
   return NormalizeDouble(v, 2);
}

int CountPullbackEntriesToday()
{
   MqlDateTime st;
   TimeToStruct(TimeCurrent(), st);
   st.hour = 0;
   st.min = 0;
   st.sec = 0;
   datetime day_start = StructToTime(st);
   if(!HistorySelect(day_start, TimeCurrent()))
      return 0;

   int cnt = 0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != g_pb_magic)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;
      cnt++;
   }
   return cnt;
}

int CountEntriesTodayByMagic(long magic)
{
   MqlDateTime st;
   TimeToStruct(TimeCurrent(), st);
   st.hour = 0; st.min = 0; st.sec = 0;
   datetime day_start = StructToTime(st);
   if(!HistorySelect(day_start, TimeCurrent()))
      return 0;
   int cnt = 0;
   int total = HistoryDealsTotal();
   for(int i = 0; i < total; i++)
   {
      ulong ticket = HistoryDealGetTicket(i);
      if(ticket == 0)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_MAGIC) != magic)
         continue;
      if(HistoryDealGetInteger(ticket, DEAL_ENTRY) != DEAL_ENTRY_IN)
         continue;
      cnt++;
   }
   return cnt;
}

bool NewSpreadTooWide()
{
   if(InpNewMaxSpreadPoints <= 0)
      return false;
   long spread = SymbolInfoInteger(g_symbol, SYMBOL_SPREAD);
   return (spread > (long)InpNewMaxSpreadPoints);
}

bool MarginOK(ENUM_ORDER_TYPE type, double lot, double price)
{
   double need = 0.0;
   if(!OrderCalcMargin(type, g_symbol, lot, price, need))
      return true;                       // kalkulasi gagal: jangan blokir order
   double free_margin = AccountInfoDouble(ACCOUNT_MARGIN_FREE);
   double buffer = free_margin * MathMax(0, InpMarginBufferPct) / 100.0;
   return (free_margin - need >= buffer);
}

//+------------------------------------------------------------------+
//| ================= STRATEGI PULLBACK TREN ======================== |
//| Tren H1: EMA cepat vs lambat + close H1 terakhir.                 |
//| Entry M5: pullback ke EMA, candle konfirmasi close, SL swing+ATR, |
//| TP R:R, trailing setelah 1R, time stop, dan exit bila tren H1     |
//| berbalik. Tidak menyentuh posisi PATTERN.                         |
//+------------------------------------------------------------------+
void TryPullback()
{
   if(!InpPullbackEnabled || !g_pullback_ready)
      return;
   if(Bars(g_symbol, PERIOD_M5) < 10)
      return;

   datetime bar1 = iTime(g_symbol, PERIOD_M5, 1);
   if(bar1 == 0 || bar1 == g_last_pb_bar)
      return;
   g_last_pb_bar = bar1;                     // evaluasi sekali per candle selesai

   if(!SessionOK() || SpreadTooWide())
      return;

   if(CountPositionsByMagic(g_pb_magic) >= MathMax(1, InpPullbackMaxPositions))
      return;
   if(CountAllEAOpenPositions() >= GlobalMaxPositions())
      return;
   if(!CanOpenGlobal())
      return;
   if(InpPullbackMaxEntriesPerDay > 0 &&
      CountPullbackEntriesToday() >= InpPullbackMaxEntriesPerDay)
      return;

   int trend = H1Trend();
   if(trend == 0)
      return;

   double ema = 0.0, atr = 0.0;
   if(!GetBufferValue(g_h_pull_ema, 1, ema) ||
      !GetBufferValue(g_h_atr, 1, atr))
      return;
   if(ema <= 0.0 || atr <= 0.0)
      return;

   double o1 = iOpen(g_symbol, PERIOD_M5, 1);
   double h1 = iHigh(g_symbol, PERIOD_M5, 1);
   double l1 = iLow(g_symbol, PERIOD_M5, 1);
   double c1 = iClose(g_symbol, PERIOD_M5, 1);
   if(o1 <= 0.0 || h1 <= 0.0 || l1 <= 0.0 || c1 <= 0.0)
      return;

   double tol = atr * InpPullbackTolATR;
   double max_ext = atr * InpPullbackMaxExtATR;
   bool setup = false;
   string side = "";

   if(trend > 0)
   {
      // Tren naik: harga menyentuh/menembus EMA lalu close kembali di atas EMA
      // dengan candle bullish. Jangan mengejar harga yang sudah terlalu jauh.
      setup = (l1 <= ema + tol && c1 > ema && c1 > o1 &&
               (c1 - ema) <= max_ext);
      side = "BUY";
   }
   else
   {
      // Tren turun: harga menyentuh/menembus EMA lalu close kembali di bawah EMA
      // dengan candle bearish.
      setup = (h1 >= ema - tol && c1 < ema && c1 < o1 &&
               (ema - c1) <= max_ext);
      side = "SELL";
   }
   if(!setup)
      return;

   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
      return;

   double entry = 0.0, sl = 0.0, tp = 0.0, risk = 0.0;
   if(side == "BUY")
   {
      double swing = MathMin(l1, MathMin(iLow(g_symbol, PERIOD_M5, 2),
                                        iLow(g_symbol, PERIOD_M5, 3)));
      entry = ask;
      sl = swing - atr * InpSLBufferATR;
      risk = entry - sl;
      if(risk <= 0.0)
         return;
      tp = entry + risk * InpRR;
   }
   else
   {
      double swing = MathMax(h1, MathMax(iHigh(g_symbol, PERIOD_M5, 2),
                                        iHigh(g_symbol, PERIOD_M5, 3)));
      entry = bid;
      sl = swing + atr * InpSLBufferATR;
      risk = sl - entry;
      if(risk <= 0.0)
         return;
      tp = entry - risk * InpRR;
   }

   if(risk < MinStopDistance())
      return;
   if(InpMaxSLATR > 0.0 && risk > atr * InpMaxSLATR)
      return;
   if(InpRR <= 0.0)
      return;

   int digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);
   risk = (side == "BUY") ? (entry - sl) : (sl - entry);
   if(risk <= 0.0)
      return;

   if(side == "BUY" && !(sl < bid && tp > ask))
      return;
   if(side == "SELL" && !(sl > ask && tp < bid))
      return;

   double lot = NormalizeLot(InpPullbackLot);
   if(lot <= 0.0)
      return;

   string id = "PB-" + IntegerToString((long)bar1) +
               (side == "BUY" ? "-B" : "-S");
   if(!IsNewSignal(id))
      return;

   string note = StringFormat(
      "tren H1=%s ema20=%.2f atr=%.2f entry=%.2f sl=%.2f tp=%.2f lot=%.2f rr=%.2f",
      (trend > 0 ? "NAIK" : "TURUN"), ema, atr, entry, sl, tp, lot, InpRR);

   if(InpPullbackShadowOnly)
   {
      LogExec("PULLBACK", id, side, 0, 0, "shadow", note + " (shadow, tanpa order)");
      return;
   }

   trade.SetExpertMagicNumber((ulong)g_pb_magic);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFillingBySymbol(g_symbol);

   bool ok = false;
   long ret = -1;
   if(side == "BUY")
   {
      ok  = trade.Buy(lot, g_symbol, 0.0, sl, tp, id);
      ret = (long)trade.ResultRetcode();
   }
   else
   {
      ok  = trade.Sell(lot, g_symbol, 0.0, sl, tp, id);
      ret = (long)trade.ResultRetcode();
   }

   string res = (ok && (ret == TRADE_RETCODE_DONE ||
                        ret == TRADE_RETCODE_PLACED)) ? "ok" : "fail";
   LogExec("PULLBACK", id, side, ret, (long)trade.ResultOrder(), res, note);

   if(res == "ok")
   {
      MarkDone(id);
      SaveState(id);
      RegisterOrder();
   }
}

void ClosePullback(ulong ticket, string side, string reason)
{
   trade.SetExpertMagicNumber((ulong)g_pb_magic);
   bool ok = trade.PositionClose(ticket);
   long ret = (long)trade.ResultRetcode();
   LogExec("PULLBACK", "PB-CLOSE", "CLOSE_" + side, ret, (long)ticket,
           ok ? "ok" : "fail", reason);
}

void ManagePullbackPositions()
{
   if(!InpPullbackEnabled)
      return;
   if(g_pb_magic <= 0)
      return;

   int trend = H1Trend();
   double atr = 0.0;
   bool atr_ok = GetBufferValue(g_h_atr, 1, atr);
   int digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != g_pb_magic)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      double entry = PositionGetDouble(POSITION_PRICE_OPEN);
      double sl = PositionGetDouble(POSITION_SL);
      double tp = PositionGetDouble(POSITION_TP);
      datetime open_t = (datetime)PositionGetInteger(POSITION_TIME);

      if(type == POSITION_TYPE_BUY)
      {
         if(trend < 0)
         {
            ClosePullback(ticket, "BUY", "exit pullback: tren H1 berbalik TURUN");
            continue;
         }
         if(InpMaxHoldMinutes > 0 &&
            (long)(TimeCurrent() - open_t) >= (long)InpMaxHoldMinutes * 60)
         {
            ClosePullback(ticket, "BUY", "exit pullback: time stop");
            continue;
         }
         if(InpUseTrailing && atr_ok && atr > 0.0 && sl > 0.0)
         {
            double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
            double risk = entry - sl;
            double profit = bid - entry;
            if(risk > 0.0 && profit >= risk * InpTrailStartR)
            {
               double new_sl = bid - atr * InpTrailATRMult;
               if(new_sl < entry)
                  new_sl = entry;                         // minimal breakeven
               double min_dist = MinStopDistance();
               if(new_sl > bid - min_dist)
                  new_sl = bid - min_dist;
               new_sl = NormalizeDouble(new_sl, digits);
               double point = SymbolInfoDouble(g_symbol, SYMBOL_POINT);
               if(point <= 0.0)
                  point = 0.01;
               if(new_sl > sl + point * 0.5 && new_sl < bid)
                  trade.PositionModify(ticket, new_sl, tp);
            }
         }
      }
      else if(type == POSITION_TYPE_SELL)
      {
         if(trend > 0)
         {
            ClosePullback(ticket, "SELL", "exit pullback: tren H1 berbalik NAIK");
            continue;
         }
         if(InpMaxHoldMinutes > 0 &&
            (long)(TimeCurrent() - open_t) >= (long)InpMaxHoldMinutes * 60)
         {
            ClosePullback(ticket, "SELL", "exit pullback: time stop");
            continue;
         }
         if(InpUseTrailing && atr_ok && atr > 0.0 && sl > 0.0)
         {
            double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
            double risk = sl - entry;
            double profit = entry - ask;
            if(risk > 0.0 && profit >= risk * InpTrailStartR)
            {
               double new_sl = ask + atr * InpTrailATRMult;
               if(new_sl > entry)
                  new_sl = entry;                         // minimal breakeven
               double min_dist = MinStopDistance();
               if(new_sl < ask + min_dist)
                  new_sl = ask + min_dist;
               new_sl = NormalizeDouble(new_sl, digits);
               double point = SymbolInfoDouble(g_symbol, SYMBOL_POINT);
               if(point <= 0.0)
                  point = 0.01;
               if(new_sl < sl - point * 0.5 && new_sl > ask)
                  trade.PositionModify(ticket, new_sl, tp);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| ================= STRATEGI MEAN REVERSION H1 =================== |
//| RSI14/Bollinger20 M5 + filter H1 EMA50/200. Entry memakai candle |
//| M5 yang sudah selesai; SL/TP ATR + time stop.                    |
//+------------------------------------------------------------------+
int ForecastDir(int &confidence)
{
   confidence = 0;
   if(!g_new_ready)
      return 0;
   if(Bars(g_symbol, PERIOD_M5) < 220)
      return 0;

   double rsi = 0.0, upper = 0.0, lower = 0.0, ema200 = 0.0;
   if(!GetBufferValue(g_h_rsi, 1, rsi) ||
      !GetBufferValue(g_h_bb, 1, upper) ||
      !GetBufferValue(g_h_bb, 2, lower) ||
      !GetBufferValue(g_h_m5_ema200, 1, ema200))
      return 0;
   double close1 = iClose(g_symbol, PERIOD_M5, 1);
   if(close1 <= 0.0 || upper <= 0.0 || lower <= 0.0 || ema200 <= 0.0)
      return 0;

   int h1 = H1Trend();
   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   int hour = dt.hour;
   bool up_med = (rsi < 30.0) || (close1 < lower);
   bool dn_med = (rsi > 70.0) || (close1 > upper);
   bool up_high = (close1 > ema200) && (rsi < 35.0) && (hour >= 0 && hour < 7);
   bool dn_high = (close1 < ema200) && (close1 > upper) && (hour >= 13 && hour < 21);

   if(up_med && !dn_med && h1 >= 0)
   {
      confidence = (up_high && h1 == 1) ? 2 : 1;
      return 1;
   }
   if(dn_med && !up_med && h1 <= 0)
   {
      confidence = (dn_high && h1 == -1) ? 2 : 1;
      return -1;
   }
   return 0;
}

bool MeanRevSetup(string &side, double &entry, double &sl, double &tp,
                  double &atr_out, double &rsi_out)
{
   side = "";
   if(!g_new_ready)
      return false;
   if(Bars(g_symbol, PERIOD_M5) < 220)
      return false;

   double rsi = 0.0, upper = 0.0, lower = 0.0, atr = 0.0;
   if(!GetBufferValue(g_h_rsi, 1, rsi) ||
      !GetBufferValue(g_h_bb, 1, upper) ||
      !GetBufferValue(g_h_bb, 2, lower) ||
      !GetBufferValue(g_h_atr, 1, atr))
      return false;
   if(atr <= 0.0 || upper <= 0.0 || lower <= 0.0)
      return false;

   double c1 = iClose(g_symbol, PERIOD_M5, 1);
   if(c1 <= 0.0)
      return false;
   int h1 = H1Trend();
   bool up = (rsi < 30.0 || c1 < lower) && h1 >= 0;
   bool dn = (rsi > 70.0 || c1 > upper) && h1 <= 0;
   if(up == dn)
      return false;

   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
      return false;

   int digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);
   if(up)
   {
      side = "BUY";
      entry = ask;
      sl = entry - atr * InpMeanRevSLATR;
      tp = entry + atr * InpMeanRevTPATR;
   }
   else
   {
      side = "SELL";
      entry = bid;
      sl = entry + atr * InpMeanRevSLATR;
      tp = entry - atr * InpMeanRevTPATR;
   }
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);
   atr_out = atr;
   rsi_out = rsi;
   double risk = (side == "BUY") ? (entry - sl) : (sl - entry);
   if(risk <= 0.0 || risk < MinStopDistance())
      return false;
   if(InpMeanRevSLATR <= 0.0 || InpMeanRevTPATR <= 0.0)
      return false;
   if(side == "BUY" && !(sl < bid && tp > ask))
      return false;
   if(side == "SELL" && !(sl > ask && tp < bid))
      return false;
   return true;
}

void TryMeanRev()
{
   if(!InpMeanRevEnabled || !g_new_ready || g_mr_magic <= 0)
      return;
   if(NewSpreadTooWide())
      return;

   datetime bar1 = iTime(g_symbol, PERIOD_M5, 1);
   if(bar1 == 0 || bar1 == g_last_mr_bar)
      return;
   g_last_mr_bar = bar1;

   if(CountPositionsByMagic(g_mr_magic) >= MathMax(1, InpMeanRevMaxPositions))
      return;
   if(CountAllEAOpenPositions() >= GlobalMaxPositions())
      return;
   if(!CanOpenGlobal())
      return;

   string side;
   double entry, sl, tp, atr, rsi;
   if(!MeanRevSetup(side, entry, sl, tp, atr, rsi))
      return;

   string id = "MR-" + IntegerToString((long)bar1) + "-" +
               (side == "BUY" ? "B" : "S");
   if(!IsNewSignal(id))
      return;

   double lot = NormalizeLot(InpMeanRevLot);
   if(lot <= 0.0)
      return;
   string note = StringFormat("RSI=%.1f atr=%.2f entry=%.2f sl=%.2f tp=%.2f lot=%.2f",
                              rsi, atr, entry, sl, tp, lot);
   if(InpMeanRevShadowOnly)
   {
      LogExec("MEANREV", id, side, 0, 0, "shadow", note + " (shadow, tanpa order)");
      return;
   }
   if(!MarginOK(side == "BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lot, entry))
   {
      Refuse("MEANREV", id, side, "margin tidak cukup setelah buffer");
      return;
   }

   trade.SetExpertMagicNumber((ulong)g_mr_magic);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFillingBySymbol(g_symbol);

   bool ok = false;
   long ret = -1;
   if(side == "BUY")
   {
      ok = trade.Buy(lot, g_symbol, 0.0, sl, tp, id);
      ret = (long)trade.ResultRetcode();
   }
   else
   {
      ok = trade.Sell(lot, g_symbol, 0.0, sl, tp, id);
      ret = (long)trade.ResultRetcode();
   }
   string res = (ok && (ret == TRADE_RETCODE_DONE ||
                        ret == TRADE_RETCODE_PLACED)) ? "ok" : "fail";
   LogExec("MEANREV", id, side, ret, (long)trade.ResultOrder(), res, note);
   if(res == "ok")
   {
      MarkDone(id);
      SaveState(id);
      RegisterOrder();
   }
}

//+------------------------------------------------------------------+
//| ================= STRATEGI SESSION BREAKOUT ===================== |
//| Range Asia 00-07 UTC; breakout candle M5 07-12 UTC; SL/TP ATR.   |
//+------------------------------------------------------------------+
bool AsiaRange(double &range_high, double &range_low)
{
   range_high = 0.0;
   range_low = 0.0;
   int start_h = (int)MathMax(0, MathMin(23, InpBreakoutRangeStartUTC));
   int end_h   = (int)MathMax(0, MathMin(23, InpBreakoutRangeEndUTC));
   if(end_h <= start_h)
      return false;

   MqlDateTime d;
   TimeToStruct(TimeGMT(), d);
   d.hour = 0; d.min = 0; d.sec = 0;
   datetime day0 = StructToTime(d);
   long offset = (long)TimeCurrent() - (long)TimeGMT();

   MqlRates rates[];
   int copied = CopyRates(g_symbol, PERIOD_M5, 1, 700, rates);
   if(copied <= 0)
      return false;
   ArraySetAsSeries(rates, false);

   int cnt = 0;
   for(int i = 0; i < copied; i++)
   {
      long gtime = (long)rates[i].time - offset;
      if(gtime < (long)day0 + (long)start_h * 3600)
         continue;
      if(gtime >= (long)day0 + (long)end_h * 3600)
         continue;
      if(cnt == 0)
      {
         range_high = rates[i].high;
         range_low = rates[i].low;
      }
      else
      {
         range_high = MathMax(range_high, rates[i].high);
         range_low = MathMin(range_low, rates[i].low);
      }
      cnt++;
   }
   return (cnt >= 12 && range_high > range_low);
}

void TryBreakout()
{
   if(!InpBreakoutEnabled || g_bo_magic <= 0)
      return;
   if(NewSpreadTooWide())
      return;

   datetime bar1 = iTime(g_symbol, PERIOD_M5, 1);
   if(bar1 == 0 || bar1 == g_last_bo_bar)
      return;
   g_last_bo_bar = bar1;

   MqlDateTime dt;
   TimeToStruct(TimeGMT(), dt);
   if(dt.hour < InpBreakoutRangeEndUTC || dt.hour >= InpBreakoutEntryEndUTC)
      return;
   if(CountPositionsByMagic(g_bo_magic) >= MathMax(1, InpBreakoutMaxPositions))
      return;
   if(CountAllEAOpenPositions() >= GlobalMaxPositions())
      return;
   if(!CanOpenGlobal())
      return;
   if(InpBreakoutMaxEntriesPerDay > 0 &&
      CountEntriesTodayByMagic(g_bo_magic) >= InpBreakoutMaxEntriesPerDay)
      return;

   double range_high = 0.0, range_low = 0.0;
   if(!AsiaRange(range_high, range_low))
      return;
   double c1 = iClose(g_symbol, PERIOD_M5, 1);
   if(c1 <= 0.0)
      return;

   string side = "";
   if(c1 > range_high)
      side = "BUY";
   else if(c1 < range_low)
      side = "SELL";
   else
      return;

   double atr = 0.0;
   if(!GetBufferValue(g_h_atr, 1, atr) || atr <= 0.0)
      return;
   if(InpBreakoutSLATR <= 0.0 || InpBreakoutTPATR <= 0.0)
      return;

   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
      return;
   double entry, sl, tp;
   int digits = (int)SymbolInfoInteger(g_symbol, SYMBOL_DIGITS);
   if(side == "BUY")
   {
      entry = ask;
      sl = entry - atr * InpBreakoutSLATR;
      tp = entry + atr * InpBreakoutTPATR;
   }
   else
   {
      entry = bid;
      sl = entry + atr * InpBreakoutSLATR;
      tp = entry - atr * InpBreakoutTPATR;
   }
   sl = NormalizeDouble(sl, digits);
   tp = NormalizeDouble(tp, digits);
   double risk = (side == "BUY") ? (entry - sl) : (sl - entry);
   if(risk <= 0.0 || risk < MinStopDistance())
      return;
   if(side == "BUY" && !(sl < bid && tp > ask))
      return;
   if(side == "SELL" && !(sl > ask && tp < bid))
      return;

   string id = "BO-" + IntegerToString((long)bar1) + "-" +
               (side == "BUY" ? "B" : "S");
   if(!IsNewSignal(id))
      return;
   double lot = NormalizeLot(InpBreakoutLot);
   if(lot <= 0.0)
      return;
   string note = StringFormat("range=%.2f-%.2f atr=%.2f entry=%.2f sl=%.2f tp=%.2f lot=%.2f",
                              range_low, range_high, atr, entry, sl, tp, lot);
   if(InpBreakoutShadowOnly)
   {
      LogExec("BREAKOUT", id, side, 0, 0, "shadow", note + " (shadow, tanpa order)");
      return;
   }
   if(!MarginOK(side == "BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lot, entry))
   {
      Refuse("BREAKOUT", id, side, "margin tidak cukup setelah buffer");
      return;
   }

   trade.SetExpertMagicNumber((ulong)g_bo_magic);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFillingBySymbol(g_symbol);
   bool ok = false;
   long ret = -1;
   if(side == "BUY")
   {
      ok = trade.Buy(lot, g_symbol, 0.0, sl, tp, id);
      ret = (long)trade.ResultRetcode();
   }
   else
   {
      ok = trade.Sell(lot, g_symbol, 0.0, sl, tp, id);
      ret = (long)trade.ResultRetcode();
   }
   string res = (ok && (ret == TRADE_RETCODE_DONE ||
                        ret == TRADE_RETCODE_PLACED)) ? "ok" : "fail";
   LogExec("BREAKOUT", id, side, ret, (long)trade.ResultOrder(), res, note);
   if(res == "ok")
   {
      MarkDone(id);
      SaveState(id);
      RegisterOrder();
   }
}

//+------------------------------------------------------------------+
//| ================= EXIT TIME STOP STRATEGI BARU ================== |
//+------------------------------------------------------------------+
void CloseStrategyPosition(ulong ticket, long magic, string strategy,
                           string side, string reason)
{
   trade.SetExpertMagicNumber((ulong)magic);
   bool ok = trade.PositionClose(ticket);
   long ret = (long)trade.ResultRetcode();
   LogExec(strategy, strategy + "-CLOSE", "CLOSE_" + side, ret,
           (long)ticket, ok ? "ok" : "fail", reason);
}

void ManageTimeStopPositions(long magic, string strategy, int hold_sec)
{
   if(magic <= 0 || hold_sec <= 0)
      return;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != magic)
         continue;
      datetime open_t = (datetime)PositionGetInteger(POSITION_TIME);
      if((long)(TimeCurrent() - open_t) >= (long)hold_sec)
      {
         string side = (PositionGetInteger(POSITION_TYPE) == POSITION_TYPE_BUY)
                       ? "BUY" : "SELL";
         CloseStrategyPosition(ticket, magic, strategy, side, "exit: time stop");
      }
   }
}

//+------------------------------------------------------------------+
//| ================= AUDIT POSISI STRATEGI BARU ==================== |
//| Keluar bila tesis entry tidak lagi valid. PATTERN/PULLBACK tidak  |
//| diubah; keduanya tetap memakai exit yang sudah ada.              |
//+------------------------------------------------------------------+
void AuditNewStrategyPositions()
{
   if(!InpAuditNewStrategies)
      return;

   int conf = 0;
   int fdir = ForecastDir(conf);
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      long magic = (long)PositionGetInteger(POSITION_MAGIC);
      if(magic != g_mr_magic && magic != g_bo_magic && magic != g_cf_magic)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      string side = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
      if(bid <= 0.0 || ask <= 0.0)
         continue;

      if(magic == g_mr_magic)
      {
         int h1 = H1Trend();
         if((side == "BUY" && h1 < 0) || (side == "SELL" && h1 > 0))
         {
            CloseStrategyPosition(ticket, g_mr_magic, "MEANREV", side,
               "exit audit: tren H1 berbalik melawan posisi");
         }
      }
      else if(magic == g_bo_magic)
      {
         double high = 0.0, low = 0.0;
         if(!AsiaRange(high, low))
            continue;
         if((side == "BUY" && bid <= high) ||
            (side == "SELL" && ask >= low))
         {
            CloseStrategyPosition(ticket, g_bo_magic, "BREAKOUT", side,
               "exit audit: harga kembali masuk range Asia (false breakout)");
         }
      }
      else if(magic == g_cf_magic && g_new_ready)
      {
         bool invalid = (fdir == 0) ||
                        (side == "BUY" && fdir < 0) ||
                        (side == "SELL" && fdir > 0);
         if(invalid)
         {
            CloseStrategyPosition(ticket, g_cf_magic, "CONFLUENCE", side,
               "exit audit: forecast tidak lagi searah");
         }
      }
   }
}

//+------------------------------------------------------------------+
//| ================= STRATEGI PATTERN (signal.txt) ================= |
//+------------------------------------------------------------------+
bool ReadSignalFile(string &header, string &sigs[], int &n_sig, bool &active)
{
   int h = FileOpen(EA_SUBFOLDER + "\\" + SIGNAL_FILE,
                    FILE_READ | FILE_TXT | FILE_ANSI | FILE_COMMON |
                    FILE_SHARE_READ | FILE_SHARE_WRITE);
   if(h == INVALID_HANDLE)
      return false;

   header = "";
   ArrayResize(sigs, 0);
   n_sig = 0;
   active = false;

   bool header_ok = false;
   while(!FileIsEnding(h))
   {
      string ln = FileReadString(h);
      if(StringLen(ln) < 3)
         continue;
      string parts[];
      int k = StringSplit(ln, ';', parts);
      if(k < 3)
         continue;
      if(parts[0] == "PATDASH")
      {
         // PATDASH;v1;DEMO_ONLY;ACTIVE;n;run_id;SYMBOL;anchor_t;rr_min;maxpos;prob_min
         header_ok = (k >= 10 && parts[2] == "DEMO_ONLY");
         active    = (k >= 4 && parts[3] == "YES");
         if(k >= 10)
         {
            int mp = (int)StringToInteger(parts[9]);
            if(mp >= 1)
               g_header_maxpos = mp;
         }
         if(k >= 8)
            g_header_anchor_t = (int)StringToInteger(parts[7]);
         if(k >= 11)
         {
            int pm = (int)StringToInteger(parts[10]);
            if(pm >= 50)
               g_header_probmin = pm;
         }
      }
      else if(parts[0] == "SIG")
      {
         int n = ArraySize(sigs);
         ArrayResize(sigs, n + 1);
         sigs[n] = ln;
         n_sig++;
      }
   }
   FileClose(h);
   return header_ok;
}

void CloseOppositePattern(const string new_side, const string id)
{
   long want_type = (new_side == "BUY") ? POSITION_TYPE_SELL : POSITION_TYPE_BUY;
   string side_lbl = (new_side == "BUY") ? "CLOSE_SELL" : "CLOSE_BUY";
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != (long)MAGIC_PATTERN)
         continue;
      if(PositionGetInteger(POSITION_TYPE) != want_type)
         continue;
      bool okc = trade.PositionClose(ticket);
      long ret = (long)trade.ResultRetcode();
      LogExec("PATTERN", "PAT-" + id, side_lbl, ret, (long)ticket,
              okc ? "ok" : "fail",
              StringFormat("exit kontradiksi: sinyal kuat %s (prob >= %d%%)",
                           new_side, g_header_probmin));
   }
}

// Tren live khusus PATTERN: bandingkan candle M5 yang sedang berjalan
// dengan EMA13 live. Ini mencegah entry BUY saat candle sudah di bawah EMA13
// (atau SELL saat candle sudah di atas EMA13) karena harga bergerak setelah
// sinyal anchor dibuat. PULLBACK tidak memakai fungsi ini.
int PatternLiveTrend()
{
   if(g_h_pattern_ema == INVALID_HANDLE)
      return 0;

   double ema[1];
   if(CopyBuffer(g_h_pattern_ema, 0, 0, 1, ema) != 1)
      return 0;

   MqlRates r[1];
   if(CopyRates(g_symbol, PERIOD_M5, 0, 1, r) != 1)
      return 0;

   if(r[0].low > ema[0])
      return 1;                       // candle live utuh di atas EMA
   if(r[0].high < ema[0])
      return -1;                      // candle live utuh di bawah EMA
   return 0;                          // EMA di dalam candle = sideways
}

void ManagePatternPositions()
{
   if(!InpPatternEnabled || !InpPatternAutoExit)
      return;
   if(CountPositionsByMagic(MAGIC_PATTERN) <= 0)
      return;

   int h1 = H1Trend();
   int live = PatternLiveTrend();
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      ulong ticket = PositionGetTicket(i);
      if(ticket == 0)
         continue;
      if(PositionGetString(POSITION_SYMBOL) != g_symbol)
         continue;
      if((long)PositionGetInteger(POSITION_MAGIC) != (long)MAGIC_PATTERN)
         continue;

      long type = PositionGetInteger(POSITION_TYPE);
      string side = (type == POSITION_TYPE_BUY) ? "BUY" : "SELL";
      datetime open_t = (datetime)PositionGetInteger(POSITION_TIME);

      if(InpPatternExitOnBadRR)
      {
         double entry = PositionGetDouble(POSITION_PRICE_OPEN);
         double sl = PositionGetDouble(POSITION_SL);
         double tp = PositionGetDouble(POSITION_TP);
         double risk = MathAbs(entry - sl);
         double reward = MathAbs(tp - entry);
         if(risk > 0.0 && reward > 0.0 &&
            reward < risk * InpPatternMinRR)
         {
            CloseStrategyPosition(ticket, MAGIC_PATTERN, "PATTERN", side,
               "exit audit: RR awal < 1 (TP lebih kecil dari SL)");
            continue;
         }
      }

      if(InpPatternMaxHoldMinutes > 0 &&
         (long)(TimeCurrent() - open_t) >= (long)InpPatternMaxHoldMinutes * 60)
      {
         CloseStrategyPosition(ticket, MAGIC_PATTERN, "PATTERN", side,
            "exit PATTERN: time stop");
         continue;
      }
      if(InpPatternExitOnTrendReversal)
      {
         if((side == "BUY" && h1 < 0 && live < 0) ||
            (side == "SELL" && h1 > 0 && live > 0))
         {
            CloseStrategyPosition(ticket, MAGIC_PATTERN, "PATTERN", side,
               "exit PATTERN: tren H1 + M5 live berbalik melawan");
         }
      }
   }
}

bool ExecuteIfNew(string line)
{
   string p[];
   if(StringSplit(line, ';', p) < 8 || p[0] != "SIG")
      return false;

   string id   = p[1];
   string side = p[2];
   if(id == g_last_done_id)
      return false;
   if(!IsNewSignal(id))
      return false;

   double entry = StringToDouble(p[3]);
   double sl    = StringToDouble(p[4]);
   double tp    = StringToDouble(p[5]);
   double lot   = StringToDouble(p[6]);
   double prob  = (ArraySize(p) >= 9) ? StringToDouble(p[8]) : 0.0;
   if(lot <= 0.0 || sl <= 0.0 || tp <= 0.0)
   {
      Refuse("PATTERN", "PAT-" + id, side, "level tidak valid (0)");
      return false;
   }

   double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
   double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
   if(bid <= 0.0 || ask <= 0.0)
   {
      Refuse("PATTERN", "PAT-" + id, side,
             "harga '" + g_symbol + "' belum tersedia — cek input SYMBOL_TRADE / Market Watch");
      return false;
   }

   // Sinyal pattern yang basi tidak boleh dieksekusi.
   if(g_header_anchor_t > 0)
   {
      int age = (int)TimeGMT() - g_header_anchor_t;
      if(age > MAX_SIGNAL_AGE_SEC)
      {
         Refuse("PATTERN", "PAT-" + id, side, StringFormat(
            "sinyal basi: umur %d dtk > %d dtk (engine server tidak memperbarui signal.txt?)",
            age, (int)MAX_SIGNAL_AGE_SEC));
         return false;
      }
   }

   // Guard tren live khusus PATTERN: sinyal yang sudah valid di anchor tetap
   // ditolak bila candle M5 saat eksekusi sudah bergerak melawan EMA13.
   if(InpPatternLiveTrendGuard)
   {
      int live_trend = PatternLiveTrend();
      if((side == "BUY" && live_trend < 0) ||
         (side == "SELL" && live_trend > 0))
      {
         Refuse("PATTERN", "PAT-" + id, side,
                side == "BUY"
                ? "candle M5 live di bawah EMA13 — BUY ditolak"
                : "candle M5 live di atas EMA13 — SELL ditolak");
         return false;
      }
   }

   // RR aktual di harga eksekusi: TP tidak boleh lebih kecil dari SL.
   double rr_risk = (side == "BUY") ? (ask - sl) : (sl - bid);
   double rr_reward = (side == "BUY") ? (tp - ask) : (bid - tp);
   if(rr_risk <= 0.0 || rr_reward <= 0.0 ||
      rr_reward < rr_risk * InpPatternMinRR)
   {
      Refuse("PATTERN", "PAT-" + id, side, StringFormat(
         "RR aktual %.2f < %.2f (TP terlalu dekat / SL terlalu jauh; risk=%.2f reward=%.2f)",
         (rr_risk > 0.0 ? rr_reward / rr_risk : 0.0), InpPatternMinRR,
         rr_risk, rr_reward));
      return false;
   }

   // Exit kontradiksi hanya untuk posisi PATTERN. Posisi PULLBACK tidak disentuh.
   if(prob >= (double)g_header_probmin && prob > 0.0)
      CloseOppositePattern(side, id);

   int maxpos = PatternMaxPositions();
   if(CountPositionsByMagic(MAGIC_PATTERN) >= maxpos)
   {
      Refuse("PATTERN", "PAT-" + id, side,
             StringFormat("posisi PATTERN >= %d (slot strategi)", maxpos));
      return false;
   }
   if(CountAllEAOpenPositions() >= GlobalMaxPositions())
   {
      Refuse("PATTERN", "PAT-" + id, side,
             StringFormat("total posisi >= %d (batas global)", GlobalMaxPositions()));
      return false;
   }
   if(!CanOpenGlobal())
   {
      Refuse("PATTERN", "PAT-" + id, side,
             StringFormat("entry per candle >= %d (batas global)",
                          (int)MathMin(5, MathMax(1, InpMaxOrdersPerCandle20))));
      return false;
   }

   bool ok = false;
   long ret = -1;
   if(side == "BUY")
   {
      if(!(sl < bid && tp > ask))
      {
         Refuse("PATTERN", "PAT-" + id, side, StringFormat(
            "SL/TP salah sisi utk BUY (bid=%.2f ask=%.2f sl=%.2f tp=%.2f)",
            bid, ask, sl, tp));
         return false;
      }
      trade.SetExpertMagicNumber((ulong)MAGIC_PATTERN);
      ok  = trade.Buy(lot, g_symbol, 0.0, sl, tp, "PAT-" + id);
      ret = (long)trade.ResultRetcode();
   }
   else if(side == "SELL")
   {
      if(!(sl > ask && tp < bid))
      {
         Refuse("PATTERN", "PAT-" + id, side, StringFormat(
            "SL/TP salah sisi utk SELL (bid=%.2f ask=%.2f sl=%.2f tp=%.2f)",
            bid, ask, sl, tp));
         return false;
      }
      trade.SetExpertMagicNumber((ulong)MAGIC_PATTERN);
      ok  = trade.Sell(lot, g_symbol, 0.0, sl, tp, "PAT-" + id);
      ret = (long)trade.ResultRetcode();
   }
   else
   {
      Refuse("PATTERN", "PAT-" + id, side, "arah tidak dikenal: " + side);
      return false;
   }

   string res = (ok && (ret == TRADE_RETCODE_DONE ||
                        ret == TRADE_RETCODE_PLACED)) ? "ok" : "fail";
   LogExec("PATTERN", "PAT-" + id, side, ret, (long)trade.ResultOrder(), res,
           StringFormat("entry=%.2f sl=%.2f tp=%.2f lot=%.2f prob=%.0f",
                        entry, sl, tp, lot, prob));
   if(res == "ok")
   {
      MarkDone(id);
      SaveState(id);
      RegisterOrder();
   }
   // Hanya order yang benar-benar sukses yang dianggap "terpakai".
   // Penolakan/gagal tidak boleh memblokir strategi PULLBACK.
   return (res == "ok");
}

bool ProcessPattern()
{
   string header, sigs[];
   int n_sig = 0;
   bool active = false;
   if(!ReadSignalFile(header, sigs, n_sig, active))
      return false;
   if(!active)
      return false;

   for(int i = 0; i < n_sig; i++)
   {
      if(ExecuteIfNew(sigs[i]))
         return true;                       // satu order per tick timer
   }
   return false;
}

//+------------------------------------------------------------------+
//| ================= STRATEGI CONFLUENCE ============================ |
//| Order tambahan hanya bila sinyal PATTERN searah forecast model.  |
//| Magic sendiri; SL/TP mengikuti sinyal PATTERN; time stop sendiri. |
//+------------------------------------------------------------------+
bool ParseSignalFields(string line, string &id, string &side,
                       double &sl, double &tp, double &prob)
{
   string p[];
   if(StringSplit(line, ';', p) < 8 || p[0] != "SIG")
      return false;
   id = p[1];
   side = p[2];
   sl = StringToDouble(p[4]);
   tp = StringToDouble(p[5]);
   prob = (ArraySize(p) >= 9) ? StringToDouble(p[8]) : 0.0;
   return (StringLen(id) > 0 && (side == "BUY" || side == "SELL"));
}

void ProcessConfluence()
{
   if(!InpConfluenceEnabled || !g_new_ready || g_cf_magic <= 0)
      return;
   if(NewSpreadTooWide())
      return;
   if(CountPositionsByMagic(g_cf_magic) >= MathMax(1, InpConfluenceMaxPositions))
      return;
   if(CountAllEAOpenPositions() >= GlobalMaxPositions())
      return;
   if(!CanOpenGlobal())
      return;

   int conf = 0;
   int fdir = ForecastDir(conf);
   if(fdir == 0)
      return;
   if(InpConfluenceRequireHigh && conf < 2)
      return;

   string header, sigs[];
   int n_sig = 0;
   bool active = false;
   if(!ReadSignalFile(header, sigs, n_sig, active) || !active)
      return;

   for(int i = 0; i < n_sig; i++)
   {
      string sig_id, side;
      double sl, tp, prob;
      if(!ParseSignalFields(sigs[i], sig_id, side, sl, tp, prob))
         continue;
      string cfid = "CF-" + sig_id;
      if(!IsNewSignal(cfid))
         continue;
      if(g_header_anchor_t > 0)
      {
         long age = (long)TimeGMT() - (long)g_header_anchor_t;
         if(age > (long)MAX_SIGNAL_AGE_SEC)
            continue;
      }
      if((side == "BUY" && fdir != 1) || (side == "SELL" && fdir != -1))
         continue;
      if(CountPositionsByMagic(g_cf_magic) >= MathMax(1, InpConfluenceMaxPositions))
         return;
      if(CountAllEAOpenPositions() >= GlobalMaxPositions())
         return;
      if(!CanOpenGlobal())
         return;

      double bid = SymbolInfoDouble(g_symbol, SYMBOL_BID);
      double ask = SymbolInfoDouble(g_symbol, SYMBOL_ASK);
      if(bid <= 0.0 || ask <= 0.0 || sl <= 0.0 || tp <= 0.0)
         continue;
      if(side == "BUY" && !(sl < bid && tp > ask))
         continue;
      if(side == "SELL" && !(sl > ask && tp < bid))
         continue;
      double lot = NormalizeLot(InpConfluenceLot);
      if(lot <= 0.0)
         return;

      string note = StringFormat("PATTERN+forecast=%s/%s entry=%.2f sl=%.2f tp=%.2f lot=%.2f",
                                 (fdir > 0 ? "NAIK" : "TURUN"),
                                 (conf >= 2 ? "high" : "medium"),
                                 (side == "BUY" ? ask : bid), sl, tp, lot);
      if(InpConfluenceShadowOnly)
      {
         LogExec("CONFLUENCE", cfid, side, 0, 0, "shadow",
                 note + " (shadow, tanpa order)");
         continue;
      }
      if(!MarginOK(side == "BUY" ? ORDER_TYPE_BUY : ORDER_TYPE_SELL, lot,
                   (side == "BUY" ? ask : bid)))
      {
         Refuse("CONFLUENCE", cfid, side, "margin tidak cukup setelah buffer");
         continue;
      }

      trade.SetExpertMagicNumber((ulong)g_cf_magic);
      trade.SetDeviationInPoints(50);
      trade.SetTypeFillingBySymbol(g_symbol);
      bool ok = false;
      long ret = -1;
      if(side == "BUY")
      {
         ok = trade.Buy(lot, g_symbol, 0.0, sl, tp, cfid);
         ret = (long)trade.ResultRetcode();
      }
      else
      {
         ok = trade.Sell(lot, g_symbol, 0.0, sl, tp, cfid);
         ret = (long)trade.ResultRetcode();
      }
      string res = (ok && (ret == TRADE_RETCODE_DONE ||
                           ret == TRADE_RETCODE_PLACED)) ? "ok" : "fail";
      LogExec("CONFLUENCE", cfid, side, ret, (long)trade.ResultOrder(), res, note);
      if(res == "ok")
      {
         MarkDone(cfid);
         SaveState(cfid);
         RegisterOrder();
      }
   }
}

//+------------------------------------------------------------------+
//| ================= EXPORTER CANDLE M5 ============================= |
//+------------------------------------------------------------------+
int ServerOffsetSec()
{
   return (int)(TimeCurrent() - TimeGMT());
}

long GmtTime(datetime server_time)
{
   return (long)server_time - ServerOffsetSec();
}

int WriteCandlesCsv(const MqlRates &rates[], const int n)
{
   string tmp_name   = InpOutFolder + "/candles_m5_" +
                       IntegerToString((long)ChartID()) + ".tmp";
   string final_name = InpOutFolder + "/candles_m5.csv";

   int h = FileOpen(tmp_name, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
   {
      Print("Gagal buka file tmp, err=", GetLastError());
      return 0;
   }
   for(int i = 0; i < n; i++)
   {
      FileWrite(h,
                GmtTime(rates[i].time),
                DoubleToString(rates[i].open,  2),
                DoubleToString(rates[i].high,  2),
                DoubleToString(rates[i].low,   2),
                DoubleToString(rates[i].close, 2),
                (long)rates[i].tick_volume,
                DoubleToString(rates[i].real_volume, 0),
                (long)rates[i].spread);
   }
   FileClose(h);

   if(!FileMove(tmp_name, FILE_COMMON, final_name, FILE_REWRITE | FILE_COMMON))
   {
      Print("Gagal FileMove, err=", GetLastError());
      return 0;
   }
   return n;
}

void WriteHeartbeat(const string status, const long bars,
                    const long last_close, const long synced)
{
   string name = InpOutFolder + "/heartbeat.txt";
   int h = FileOpen(name, FILE_WRITE | FILE_CSV | FILE_ANSI | FILE_COMMON, ';');
   if(h == INVALID_HANDLE)
      return;
   FileWrite(h, status, g_symbol, "M5", bars, last_close, synced,
             (long)TimeCurrent());
   FileClose(h);
}

void TryExport(bool force)
{
   if(Bars(g_symbol, PERIOD_M5) < 10)
      return;

   datetime current_bar = iTime(g_symbol, PERIOD_M5, 0);
   if(!force && g_last_write != 0 && current_bar == g_last_write)
      return;

   MqlRates rates[];
   ArraySetAsSeries(rates, false);
   int copied = CopyRates(g_symbol, PERIOD_M5, 1, InpMaxBars, rates);
   if(copied <= 0)
   {
      WriteHeartbeat("ERROR", copied, 0, 0);
      return;
   }

   int written = WriteCandlesCsv(rates, copied);
   if(written > 0)
   {
      g_last_write = current_bar;
      datetime last_close = rates[copied - 1].time;
      WriteHeartbeat("OK", written, GmtTime(last_close), (long)TimeGMT());
   }
}

//+------------------------------------------------------------------+
//| ================= PERAN INSTANCE (anti EA ganda) ================= |
//+------------------------------------------------------------------+
void UpdateInstanceRole()
{
   if(g_instance_file == "")
      return;

   long my_id = (long)ChartID();
   long now = (long)TimeGMT();

   int h = FileOpen(g_instance_file,
                    FILE_WRITE | FILE_TXT | FILE_ANSI | FILE_COMMON);
   if(h != INVALID_HANDLE)
   {
      FileWriteString(h, IntegerToString(my_id) + ";" + IntegerToString(now));
      FileClose(h);
   }

   long best = my_id;
   string fname;
   long search = FileFindFirst(InpOutFolder + "/" + INSTANCE_PREFIX + "*.txt",
                               fname, FILE_COMMON);
   if(search != INVALID_HANDLE)
   {
      do
      {
         string full = fname;
         if(StringFind(full, "/") < 0)
            full = InpOutFolder + "/" + fname;
         int fh = FileOpen(full, FILE_READ | FILE_TXT | FILE_ANSI |
                           FILE_COMMON | FILE_SHARE_READ);
         if(fh != INVALID_HANDLE)
         {
            string s = FileReadString(fh);
            FileClose(fh);
            string p[];
            if(StringSplit(s, ';', p) >= 2)
            {
               long oid = StringToInteger(p[0]);
               long ots = StringToInteger(p[1]);
               if(oid > 0 && (now - ots) <= PRIMARY_FRESH_SEC && oid < best)
                  best = oid;
            }
         }
      } while(FileFindNext(search, fname));
      FileClose((int)search);
   }

   bool primary = (best == my_id);
   if(!g_role_known || primary != g_is_primary)
   {
      g_role_known = true;
      g_is_primary = primary;
      if(primary)
         LogExec("GLOBAL", "-", "-", 0, 0, "info",
                 "instance PRIMER chart=" + IntegerToString(my_id) +
                 " - trading & ekspor aktif");
      else
         LogExec("GLOBAL", "-", "-", 0, 0, "info",
                 "instance SEKUNDER chart=" + IntegerToString(my_id) +
                 " - nonaktif (primer chart=" + IntegerToString(best) + ")");
   }
}

//+------------------------------------------------------------------+
//| Cari simbol emas yang tersedia di broker (XAUUSDc/XAUUSDb/GOLD). |
//+------------------------------------------------------------------+
string FindGoldSymbol()
{
   for(int i = 0; i < SymbolsTotal(false); i++)
   {
      string name = SymbolName(i, false);
      string upper = name;
      StringToUpper(upper);
      if(StringFind(upper, "XAUUSD") >= 0 || StringFind(upper, "GOLD") >= 0)
      {
         if(SymbolSelect(name, true))
            return name;
      }
   }
   return "";
}

//+------------------------------------------------------------------+
//| ================= LIFECYCLE ===================================== |
//+------------------------------------------------------------------+
int OnInit()
{
   g_symbol = SYMBOL_TRADE;
   bool symbol_ok = SymbolSelect(g_symbol, true);
   if(InpAutoSymbol && !symbol_ok)
   {
      string auto_symbol = FindGoldSymbol();
      if(auto_symbol != "")
      {
         g_symbol = auto_symbol;
         symbol_ok = true;
         LogExec("GLOBAL", "BOOT", "-", 0, 0, "info",
                 "symbol auto terdeteksi: " + g_symbol);
      }
   }
   if(!symbol_ok)
   {
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "symbol '" + g_symbol + "' TIDAK ADA — fallback ke symbol chart '" +
              _Symbol + "'");
      g_symbol = _Symbol;
      SymbolSelect(g_symbol, true);
   }

   g_pb_magic = (long)InpPullbackMagic;
   if(g_pb_magic <= 0 || g_pb_magic == (long)MAGIC_PATTERN)
   {
      g_pb_magic = 20261113;
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "magic pullback tidak valid/bentrok — dipakai 20261113");
   }

   g_mr_magic = (long)InpMeanRevMagic;
   if(g_mr_magic <= 0 || g_mr_magic == (long)MAGIC_PATTERN ||
      g_mr_magic == g_pb_magic)
   {
      g_mr_magic = 20261114;
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "magic MEANREV tidak valid/bentrok — dipakai 20261114");
   }
   g_bo_magic = (long)InpBreakoutMagic;
   if(g_bo_magic <= 0 || g_bo_magic == (long)MAGIC_PATTERN ||
      g_bo_magic == g_pb_magic || g_bo_magic == g_mr_magic)
   {
      g_bo_magic = 20261115;
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "magic BREAKOUT tidak valid/bentrok — dipakai 20261115");
   }
   g_cf_magic = (long)InpConfluenceMagic;
   if(g_cf_magic <= 0 || g_cf_magic == (long)MAGIC_PATTERN ||
      g_cf_magic == g_pb_magic || g_cf_magic == g_mr_magic ||
      g_cf_magic == g_bo_magic)
   {
      g_cf_magic = 20261116;
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "magic CONFLUENCE tidak valid/bentrok — dipakai 20261116");
   }

   g_h_ema_fast = iMA(g_symbol, PERIOD_H1, InpTrendFastEMA, 0,
                      MODE_EMA, PRICE_CLOSE);
   g_h_ema_slow = iMA(g_symbol, PERIOD_H1, InpTrendSlowEMA, 0,
                      MODE_EMA, PRICE_CLOSE);
   g_h_pull_ema = iMA(g_symbol, PERIOD_M5, InpPullbackEMA, 0,
                      MODE_EMA, PRICE_CLOSE);
   g_h_atr = iATR(g_symbol, PERIOD_M5, InpATRPeriod);
   g_h_pattern_ema = iMA(g_symbol, PERIOD_M5, InpPatternTrendPeriod, 0,
                         MODE_EMA, PRICE_CLOSE);
   g_h_rsi = iRSI(g_symbol, PERIOD_M5, 14, PRICE_CLOSE);
   g_h_bb = iBands(g_symbol, PERIOD_M5, 20, 0, 2.0, PRICE_CLOSE);
   g_h_m5_ema200 = iMA(g_symbol, PERIOD_M5, 200, 0,
                       MODE_EMA, PRICE_CLOSE);

   g_pullback_ready = (g_h_ema_fast != INVALID_HANDLE &&
                       g_h_ema_slow != INVALID_HANDLE &&
                       g_h_pull_ema != INVALID_HANDLE &&
                       g_h_atr != INVALID_HANDLE);
   g_new_ready = (g_h_ema_fast != INVALID_HANDLE &&
                  g_h_ema_slow != INVALID_HANDLE &&
                  g_h_atr != INVALID_HANDLE &&
                  g_h_rsi != INVALID_HANDLE &&
                  g_h_bb != INVALID_HANDLE &&
                  g_h_m5_ema200 != INVALID_HANDLE);

   trade.SetExpertMagicNumber((ulong)MAGIC_PATTERN);
   trade.SetDeviationInPoints(50);
   trade.SetTypeFillingBySymbol(g_symbol);

   g_instance_file = InpOutFolder + "/" + INSTANCE_PREFIX +
                     IntegerToString((long)ChartID()) + ".txt";
   LoadState();
   UpdateInstanceRole();

   // Jangan langsung entry pada candle yang sudah selesai sebelum EA hidup.
   g_last_pb_bar = iTime(g_symbol, PERIOD_M5, 1);
   g_last_mr_bar = g_last_pb_bar;
   g_last_bo_bar = g_last_pb_bar;

   EventSetTimer(1);
   if(g_is_primary)
      TryExport(true);

   LogExec("GLOBAL", "BOOT", "-", 0, 0, "ok",
           "EA gabungan mulai; akun=" + AccountModeName() +
           " symbol=" + g_symbol +
           " pattern_magic=" + IntegerToString(MAGIC_PATTERN) +
           " pullback_magic=" + IntegerToString(g_pb_magic) +
           " meanrev_magic=" + IntegerToString(g_mr_magic) +
           " breakout_magic=" + IntegerToString(g_bo_magic) +
           " confluence_magic=" + IntegerToString(g_cf_magic) +
           " pattern=" + (InpPatternEnabled ? "ON" : "OFF") +
           " pattern_auto_exit=" + (InpPatternAutoExit ? "ON" : "OFF") +
           " pattern_min_rr=" + DoubleToString(InpPatternMinRR, 2) +
           " pullback=" + (InpPullbackEnabled ? "ON" : "OFF") +
           " meanrev=" + (InpMeanRevEnabled ? "ON" : "OFF") +
           " breakout=" + (InpBreakoutEnabled ? "ON" : "OFF") +
           " confluence=" + (InpConfluenceEnabled ? "ON" : "OFF") +
           " slots=3+2+5+5+5 / global=" + IntegerToString(GlobalMaxPositions()));

   if(!g_pullback_ready)
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "indikator pullback gagal dibuat — strategi PULLBACK nonaktif");
   if(!g_new_ready)
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "indikator MEANREV/BREAKOUT/CONFLUENCE gagal dibuat — strategi baru nonaktif");
   if(InpPatternEnabled && InpPatternLiveTrendGuard &&
      g_h_pattern_ema == INVALID_HANDLE)
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "EMA13 live PATTERN gagal dibuat — guard tren live PATTERN nonaktif");
   if(IsNettingAccount())
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "akun NETTING: posisi XAUUSD bisa digabung broker; identitas magic " +
              "tidak sepenuhnya terpisah. Gunakan akun hedging untuk isolasi penuh.");
   if(InpPullbackEnabled && Bars(g_symbol, PERIOD_H1) < InpTrendSlowEMA + 2)
      LogExec("GLOBAL", "BOOT", "-", 0, 0, "warn",
              "riwayat H1 belum cukup untuk EMA " +
              IntegerToString(InpTrendSlowEMA) +
              " — pullback menunggu data");

   return(INIT_SUCCEEDED);
}

void OnDeinit(const int reason)
{
   EventKillTimer();
   if(g_instance_file != "")
      FileDelete(g_instance_file, FILE_COMMON);

   if(g_h_ema_fast != INVALID_HANDLE)
      IndicatorRelease(g_h_ema_fast);
   if(g_h_ema_slow != INVALID_HANDLE)
      IndicatorRelease(g_h_ema_slow);
   if(g_h_pull_ema != INVALID_HANDLE)
      IndicatorRelease(g_h_pull_ema);
   if(g_h_atr != INVALID_HANDLE)
      IndicatorRelease(g_h_atr);
   if(g_h_pattern_ema != INVALID_HANDLE)
      IndicatorRelease(g_h_pattern_ema);
   if(g_h_rsi != INVALID_HANDLE)
      IndicatorRelease(g_h_rsi);
   if(g_h_bb != INVALID_HANDLE)
      IndicatorRelease(g_h_bb);
   if(g_h_m5_ema200 != INVALID_HANDLE)
      IndicatorRelease(g_h_m5_ema200);
}

void OnTick()
{
   if(g_is_primary)
      TryExport(false);
}

void OnTimer()
{
   UpdateInstanceRole();
   if(!g_is_primary)
      return;

   TryExport(false);
   WritePositionsSnapshot();
   WritePnlSnapshot();

   // Pengaman wajib: akun harus DEMO.
   if(!IsDemoAccountSafe())
   {
      RefuseOnce("AKUN BUKAN DEMO — eksekusi ditolak (wajib demo)");
      return;
   }

   // Kelola exit/trailing semua strategi lebih dulu.
   ManagePullbackPositions();
   ManagePatternPositions();
   ManageTimeStopPositions(g_mr_magic, "MEANREV",
                           MathMax(1, InpMeanRevHoldBars) * 300);
   ManageTimeStopPositions(g_bo_magic, "BREAKOUT",
                           MathMax(1, InpBreakoutHoldBars) * 300);
   ManageTimeStopPositions(g_cf_magic, "CONFLUENCE",
                           MathMax(1, InpConfluenceMaxHoldMinutes) * 60);
   AuditNewStrategyPositions();

   // PULLBACK tetap dievaluasi lebih dulu dan aturannya tidak diubah.
   if(InpPullbackEnabled)
      TryPullback();

   if(InpPatternEnabled)
      ProcessPattern();

   if(InpMeanRevEnabled)
      TryMeanRev();
   if(InpBreakoutEnabled)
      TryBreakout();
   if(InpConfluenceEnabled)
      ProcessConfluence();
}
//+------------------------------------------------------------------+
