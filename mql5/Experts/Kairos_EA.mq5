//+------------------------------------------------------------------+
//|                                                    Kairos_EA.mq5 |
//|                             Copyright 2026, Antigravity Trading  |
//|                                  https://github.com/shiyu-coder  |
//+------------------------------------------------------------------+
#property copyright   "Copyright 2026, Antigravity Trading"
#property link        "https://github.com/shiyu-coder"
#property version     "1.00"
#property description "Kairos Expert Advisor: Native MQL5 port of the K-line momentum & pattern heuristic engine"
#property description "Analyzes multiscale momentum (5/10/20), wick rejection, candle series and volume bursts."

#include <Trade\Trade.mqh>
#include <Trade\PositionInfo.mqh>
#include <Trade\SymbolInfo.mqh>

//+------------------------------------------------------------------+
//| Input Parameters                                                 |
//+------------------------------------------------------------------+
input group "=== Kairos Engine Parameters ==="
input int      InpWindowSize           = 60;     // Lookback window (candles)
input int      InpForecastHorizon      = 10;     // Forecast horizon (candles ahead)
input double   InpConfidenceThreshold  = 0.40;   // Minimum confidence to trade (0.0 - 1.0)
input double   InpScoreThreshold       = 0.25;   // Score threshold for BUY/SELL (+/- 0.25)
input double   InpMinSlAtrMultiplier   = 1.5;    // Minimum SL multiplier for ATR (14)

input group "=== Risk & Money Management ==="
input bool     InpUseRiskPercent       = false;  // Use % equity risk (true) or fixed lot (false)
input double   InpRiskPercent          = 1.0;    // Risk percent per trade (% of equity)
input double   InpFixedLot             = 0.01;   // Fixed lot size
input int      InpMaxPositionsBuy      = 1;      // Max open BUY positions for symbol
input int      InpMaxPositionsSell     = 1;      // Max open SELL positions for symbol

input group "=== Trade Protection & Trailing ==="
input bool     InpTrailingStop         = true;   // Enable Trailing Stop
input int      InpTrailingActivationPips = 30;   // Trailing activation in pips
input int      InpTrailingStopPips     = 20;     // Trailing distance in pips
input ulong    InpMagicNumber          = 112233; // Magic Number
input ulong    InpSlippage             = 10;     // Max slippage (points)
input string   InpTradeComment         = "Kairos_EA"; // Order comment

//+------------------------------------------------------------------+
//| Global Variables                                                 |
//+------------------------------------------------------------------+
CTrade         m_trade;
CPositionInfo  m_position;
CSymbolInfo    m_symbol;
datetime       m_last_bar_time = 0;

//+------------------------------------------------------------------+
//| Expert initialization function                                   |
//+------------------------------------------------------------------+
int OnInit()
{
   if(!m_symbol.Name(_Symbol))
   {
      Print("Failed to initialize CSymbolInfo for ", _Symbol);
      return INIT_FAILED;
   }
   m_symbol.Refresh();

   m_trade.SetExpertMagicNumber(InpMagicNumber);
   m_trade.SetDeviationInPoints(InpSlippage);
   m_trade.SetTypeFillingBySymbol(_Symbol);

   Print("Kairos EA successfully initialized on ", _Symbol, " ", EnumToString(_Period));
   Print("Engine: Window=", InpWindowSize, ", Horizon=", InpForecastHorizon, 
         ", MinConfidence=", InpConfidenceThreshold, ", ScoreThreshold=", InpScoreThreshold);

   return INIT_SUCCEEDED;
}

//+------------------------------------------------------------------+
//| Expert deinitialization function                                 |
//+------------------------------------------------------------------+
void OnDeinit(const int reason)
{
   Comment("");
   Print("Kairos EA deinitialized (reason: ", reason, ")");
}

//+------------------------------------------------------------------+
//| Check if a new candle has opened                                 |
//+------------------------------------------------------------------+
bool IsNewBar()
{
   datetime current_bar_time = iTime(_Symbol, _Period, 0);
   if(current_bar_time == 0) return false;
   if(current_bar_time != m_last_bar_time)
   {
      m_last_bar_time = current_bar_time;
      return true;
   }
   return false;
}

//+------------------------------------------------------------------+
//| Count open positions for this symbol and magic number            |
//+------------------------------------------------------------------+
void CountOpenPositions(int &buy_count, int &sell_count)
{
   buy_count = 0;
   sell_count = 0;
   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(m_position.SelectByIndex(i))
      {
         if(m_position.Symbol() == _Symbol && m_position.Magic() == InpMagicNumber)
         {
            if(m_position.PositionType() == POSITION_TYPE_BUY)
               buy_count++;
            else if(m_position.PositionType() == POSITION_TYPE_SELL)
               sell_count++;
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Calculate Lot Size based on risk or fixed                        |
//+------------------------------------------------------------------+
double CalculateLotSize(double sl_distance_points)
{
   m_symbol.Refresh();
   double min_lot = m_symbol.LotsMin();
   double max_lot = m_symbol.LotsMax();
   double lot_step = m_symbol.LotsStep();

   if(!InpUseRiskPercent)
   {
      double lot = MathMax(min_lot, MathMin(max_lot, InpFixedLot));
      return MathFloor(lot / lot_step) * lot_step;
   }

   double equity = AccountInfoDouble(ACCOUNT_EQUITY);
   double risk_amount = equity * (InpRiskPercent / 100.0);
   double tick_value = m_symbol.TickValue();
   double tick_size = m_symbol.TickSize();
   double point = m_symbol.Point();

   if(tick_value <= 0 || tick_size <= 0 || sl_distance_points <= 0)
   {
      return min_lot;
   }

   double loss_per_lot = (sl_distance_points * point / tick_size) * tick_value;
   if(loss_per_lot <= 0) return min_lot;

   double raw_lot = risk_amount / loss_per_lot;
   raw_lot = MathMax(min_lot, MathMin(max_lot, raw_lot));
   return MathFloor(raw_lot / lot_step) * lot_step;
}

//+------------------------------------------------------------------+
//| Manage Trailing Stop for open positions                          |
//+------------------------------------------------------------------+
void ApplyTrailingStop()
{
   if(!InpTrailingStop) return;

   m_symbol.Refresh();
   double point = m_symbol.Point();
   int digits = (int)m_symbol.Digits();
   double act_distance = InpTrailingActivationPips * 10.0 * point;
   double trail_distance = InpTrailingStopPips * 10.0 * point;

   for(int i = PositionsTotal() - 1; i >= 0; i--)
   {
      if(!m_position.SelectByIndex(i)) continue;
      if(m_position.Symbol() != _Symbol || m_position.Magic() != InpMagicNumber) continue;

      ulong ticket = m_position.Ticket();
      double open_price = m_position.PriceOpen();
      double current_sl = m_position.StopLoss();
      double current_tp = m_position.TakeProfit();

      if(m_position.PositionType() == POSITION_TYPE_BUY)
      {
         double current_bid = m_symbol.Bid();
         if(current_bid - open_price >= act_distance)
         {
            double new_sl = NormalizeDouble(current_bid - trail_distance, digits);
            if(new_sl > current_sl + point)
            {
               m_trade.PositionModify(ticket, new_sl, current_tp);
            }
         }
      }
      else if(m_position.PositionType() == POSITION_TYPE_SELL)
      {
         double current_ask = m_symbol.Ask();
         if(open_price - current_ask >= act_distance)
         {
            double new_sl = NormalizeDouble(current_ask + trail_distance, digits);
            if(current_sl == 0.0 || new_sl < current_sl - point)
            {
               m_trade.PositionModify(ticket, new_sl, current_tp);
            }
         }
      }
   }
}

//+------------------------------------------------------------------+
//| Kairos Feature Analysis and Prediction Core                      |
//+------------------------------------------------------------------+
struct KairosPrediction
{
   int      signal;         // 1 = BUY, -1 = SELL, 0 = HOLD
   double   confidence;     // 0.0 .. 0.99
   double   total_score;    // -1.0 .. +1.0
   double   target_price;
   double   stop_loss;
   double   take_profit;
   string   reasons;
};

bool RunKairosAnalysis(KairosPrediction &out_result)
{
   out_result.signal = 0;
   out_result.confidence = 0.0;
   out_result.total_score = 0.0;
   out_result.target_price = 0.0;
   out_result.stop_loss = 0.0;
   out_result.take_profit = 0.0;
   out_result.reasons = "";

   int needed = InpWindowSize + 15;
   MqlRates rates[];
   ArraySetAsSeries(rates, false); // Index 0 is oldest, index copied-1 is last completed bar
   int copied = CopyRates(_Symbol, _Period, 1, InpWindowSize, rates);
   if(copied < InpWindowSize)
   {
      out_result.reasons = "Insufficient bars";
      return false;
   }

   int n = InpWindowSize;
   double body_pct[];
   double upper_wick_pct[];
   double lower_wick_pct[];
   double returns[];
   double volumes[];
   double tr[];

   ArrayResize(body_pct, n);
   ArrayResize(upper_wick_pct, n);
   ArrayResize(lower_wick_pct, n);
   ArrayResize(returns, n);
   ArrayResize(volumes, n);
   ArrayResize(tr, n);

   // 1. Data preprocessing
   double vol_sum = 0.0;
   for(int i = 0; i < n; i++)
   {
      double o = rates[i].open;
      double h = rates[i].high;
      double l = rates[i].low;
      double c = rates[i].close;
      double v = (double)rates[i].tick_volume;

      double o_safe = (o == 0.0) ? 1e-6 : o;
      body_pct[i] = (c - o) / o_safe;
      upper_wick_pct[i] = (h - MathMax(o, c)) / o_safe;
      lower_wick_pct[i] = (MathMin(o, c) - l) / o_safe;
      volumes[i] = v;
      vol_sum += v;

      if(i == 0)
      {
         returns[i] = 0.0;
         tr[i] = h - l;
      }
      else
      {
         double prev_c = (rates[i-1].close == 0.0) ? 1e-6 : rates[i-1].close;
         returns[i] = (c - rates[i-1].close) / prev_c;
         double tr1 = h - l;
         double tr2 = MathAbs(h - rates[i-1].close);
         double tr3 = MathAbs(l - rates[i-1].close);
         tr[i] = MathMax(tr1, MathMax(tr2, tr3));
      }
   }

   // Volume Z-score
   double vol_mean = vol_sum / (double)n;
   double vol_variance = 0.0;
   for(int i = 0; i < n; i++)
   {
      vol_variance += MathPow(volumes[i] - vol_mean, 2);
   }
   double vol_std = MathSqrt(vol_variance / (double)n) + 1e-8;
   double volume_z_last = (volumes[n - 1] - vol_mean) / vol_std;

   // Volatility (mean True Range % of last close)
   double last_close = rates[n - 1].close;
   double tr_sum = 0.0;
   for(int i = 1; i < n; i++) tr_sum += tr[i];
   double mean_tr = tr_sum / (double)(n - 1);
   double volatility = mean_tr / (last_close + 1e-6);
   if(volatility <= 0.0) volatility = 0.001;

   // 2. Multiscale momentum (5, 10, 20)
   double mom5 = 0.0, mom10 = 0.0, mom20 = 0.0;
   for(int i = n - 5; i < n; i++)  mom5 += returns[i];
   for(int i = n - 10; i < n; i++) mom10 += returns[i];
   for(int i = n - 20; i < n; i++) mom20 += returns[i];
   double momentum_score = 0.5 * mom5 + 0.3 * mom10 + 0.2 * mom20;

   // 3. Candle structure (last 3 bodies)
   int bullish = 0, bearish = 0;
   for(int i = n - 3; i < n; i++)
   {
      if(body_pct[i] > 0.0) bullish++;
      else if(body_pct[i] < 0.0) bearish++;
   }

   double candle_score = 0.0;
   string reasons_list = "";
   if(bullish == 3)
   {
      candle_score += 0.3;
      reasons_list += "3 consecutive bullish candles; ";
   }
   else if(bearish == 3)
   {
      candle_score -= 0.3;
      reasons_list += "3 consecutive bearish candles; ";
   }

   // Wick rejection on last bar
   double last_upper_wick = upper_wick_pct[n - 1];
   double last_lower_wick = lower_wick_pct[n - 1];
   double last_body = body_pct[n - 1];

   if(last_lower_wick > 2.0 * MathAbs(last_body) && last_lower_wick > 0.001)
   {
      candle_score += 0.2;
      reasons_list += "strong lower shadow rejection; ";
   }
   else if(last_upper_wick > 2.0 * MathAbs(last_body) && last_upper_wick > 0.001)
   {
      candle_score -= 0.2;
      reasons_list += "strong upper shadow rejection; ";
   }

   // 4. Volume confirmation
   double volume_bias = 0.0;
   if(volume_z_last > 1.0)
   {
      if(returns[n - 1] > 0.0)
      {
         volume_bias = 0.2;
         reasons_list += "high volume breakout UP; ";
      }
      else if(returns[n - 1] < 0.0)
      {
         volume_bias = -0.2;
         reasons_list += "high volume breakdown DOWN; ";
      }
   }

   // 5. Total score & Confidence
   double total_score = (momentum_score * 50.0) + candle_score + volume_bias;
   total_score = MathMax(-1.0, MathMin(1.0, total_score));

   int sign_mom = (momentum_score > 0.0) ? 1 : ((momentum_score < 0.0) ? -1 : 0);
   int sign_cnd = (candle_score > 0.0) ? 1 : ((candle_score < 0.0) ? -1 : 0);
   double consistency = (sign_mom == sign_cnd && MathAbs(candle_score) > 0.0) ? 1.0 : 0.7;
   double raw_conf = MathAbs(total_score) * 0.75 + (0.25 * consistency);
   double confidence = MathMax(0.2, MathMin(0.95, raw_conf));

   // 6. Target price, SL, TP
   int atr_period = MathMin(14, n - 1);
   double atr_sum = 0.0;
   for(int i = n - atr_period; i < n; i++) atr_sum += tr[i];
   double atr = atr_sum / (double)atr_period;

   double move_pct = 0.003 * InpForecastHorizon * (MathAbs(total_score) + 0.35);
   double sl_distance = MathMax(last_close * MathMax(volatility, 0.001) * 1.5, atr * InpMinSlAtrMultiplier);

   int digits = (int)m_symbol.Digits();
   out_result.confidence = confidence;
   out_result.total_score = total_score;

   if(total_score > InpScoreThreshold)
   {
      out_result.signal = 1; // BUY
      out_result.target_price = NormalizeDouble(last_close * (1.0 + move_pct), digits);
      out_result.stop_loss = NormalizeDouble(last_close - sl_distance, digits);
      out_result.take_profit = out_result.target_price;
      reasons_list += StringFormat("bullish momentum (%+.2f)", total_score);
   }
   else if(total_score < -InpScoreThreshold)
   {
      out_result.signal = -1; // SELL
      out_result.target_price = NormalizeDouble(last_close * (1.0 - move_pct), digits);
      out_result.stop_loss = NormalizeDouble(last_close + sl_distance, digits);
      out_result.take_profit = out_result.target_price;
      reasons_list += StringFormat("bearish momentum (%+.2f)", total_score);
   }
   else
   {
      out_result.signal = 0; // HOLD
      reasons_list += "consolidation pattern";
   }

   out_result.reasons = reasons_list;
   return true;
}

//+------------------------------------------------------------------+
//| Update on-chart info dashboard                                   |
//+------------------------------------------------------------------+
void UpdateDashboard(const KairosPrediction &pred, int buy_count, int sell_count)
{
   string signal_str = "HOLD ⚪";
   if(pred.signal == 1) signal_str = "BUY 🟢";
   else if(pred.signal == -1) signal_str = "SELL 🔴";

   string comment = "========================================\n"
                  + "         KAIROS EXPERT ADVISOR (MT5)    \n"
                  + "========================================\n"
                  + StringFormat("Symbol: %s | Timeframe: %s\n", _Symbol, EnumToString(_Period))
                  + StringFormat("Signal: %s (Confidence: %.1f%%)\n", signal_str, pred.confidence * 100.0)
                  + StringFormat("Score: %+.3f (Threshold: +/-%.2f)\n", pred.total_score, InpScoreThreshold)
                  + StringFormat("Target Price: %.5f\n", pred.target_price)
                  + StringFormat("Stop Loss:    %.5f\n", pred.stop_loss)
                  + StringFormat("Take Profit:  %.5f\n", pred.take_profit)
                  + StringFormat("Active Positions: BUY=%d, SELL=%d\n", buy_count, sell_count)
                  + StringFormat("Reasons: %s\n", pred.reasons)
                  + "========================================";

   Comment(comment);
}

//+------------------------------------------------------------------+
//| Expert tick function                                             |
//+------------------------------------------------------------------+
void OnTick()
{
   // Always check trailing stop on every tick
   ApplyTrailingStop();

   // Run prediction only when a new candle opens
   if(!IsNewBar()) return;

   int buy_positions = 0, sell_positions = 0;
   CountOpenPositions(buy_positions, sell_positions);

   KairosPrediction pred;
   if(!RunKairosAnalysis(pred))
   {
      Print("Kairos analysis failed: ", pred.reasons);
      return;
   }

   UpdateDashboard(pred, buy_positions, sell_positions);

   // Hard gate on confidence threshold
   if(pred.confidence < InpConfidenceThreshold)
   {
      PrintFormat("Kairos: Signal %d filtered out (Confidence %.2f < Threshold %.2f)",
                  pred.signal, pred.confidence, InpConfidenceThreshold);
      return;
   }

   m_symbol.Refresh();
   double point = m_symbol.Point();

   // Execute BUY order
   if(pred.signal == 1)
   {
      if(buy_positions >= InpMaxPositionsBuy)
      {
         PrintFormat("Kairos BUY signal ignored: Max BUY positions reached (%d/%d)",
                     buy_positions, InpMaxPositionsBuy);
         return;
      }

      double ask = m_symbol.Ask();
      double sl_distance_points = (ask - pred.stop_loss) / point;
      double lot = CalculateLotSize(sl_distance_points);

      PrintFormat("Kairos BUY Order: Lot=%.2f, Price=%.5f, SL=%.5f, TP=%.5f, Conf=%.1f%%",
                  lot, ask, pred.stop_loss, pred.take_profit, pred.confidence * 100.0);

      m_trade.Buy(lot, _Symbol, ask, pred.stop_loss, pred.take_profit, InpTradeComment);
   }
   // Execute SELL order
   else if(pred.signal == -1)
   {
      if(sell_positions >= InpMaxPositionsSell)
      {
         PrintFormat("Kairos SELL signal ignored: Max SELL positions reached (%d/%d)",
                     sell_positions, InpMaxPositionsSell);
         return;
      }

      double bid = m_symbol.Bid();
      double sl_distance_points = (pred.stop_loss - bid) / point;
      double lot = CalculateLotSize(sl_distance_points);

      PrintFormat("Kairos SELL Order: Lot=%.2f, Price=%.5f, SL=%.5f, TP=%.5f, Conf=%.1f%%",
                  lot, bid, pred.stop_loss, pred.take_profit, pred.confidence * 100.0);

      m_trade.Sell(lot, _Symbol, bid, pred.stop_loss, pred.take_profit, InpTradeComment);
   }
}
//+------------------------------------------------------------------+
