//+------------------------------------------------------------------+
//| YugenChartBridgeService.mq5                                      |
//| Named-pipe client service for the Yugen MCP chart bridge.       |
//|                                                                  |
//| Architecture                                                     |
//|   Python MCP  = named-pipe SERVER (CreateNamedPipe/Connect)      |
//|   This service = named-pipe CLIENT (FileOpen with FILE_BIN)      |
//|                                                                  |
//| Lifecycle (one FileOpen per request — matches Python disconnect) |
//|   while(!IsStopped())                                            |
//|     FileOpen → read one JSON line → process → write ACK → Close |
//|                                                                  |
//| Wire format                                                      |
//|   UTF-8 newline-delimited JSON, same contract as chart_bridge.py |
//|                                                                  |
//| HMAC                                                             |
//|   HMAC-SHA256 via CryptEncode(CRYPT_HASH_SHA256, ...); lowercase |
//|   hex 64 chars; golden vectors in test_hmac_golden_vectors.py.  |
//|                                                                  |
//| Manual QA gate — compile and test on Windows with MetaEditor.   |
//| This file is NOT compiled in CI (MQL5 = Windows-only).          |
//+------------------------------------------------------------------+
#property service
#property version   "1.00"
#property strict
#property description "Yugen chart bridge named-pipe client service."

input string PipeName    = "yugen_chart_bridge"; // Pipe name (bare, no \\.\\pipe\\ prefix)
input string SharedSecret = "";                  // REQUIRED: must match YUGEN_MT5_CHART_SHARED_SECRET

#define SCHEMA_VERSION  "2026-05-31"
#define YUGEN_PREFIX    "yugen_"
#define HMAC_BLOCK_SIZE 64

//+------------------------------------------------------------------+
//| Request envelope parsed from the Python client                   |
//+------------------------------------------------------------------+
struct ChartBridgeRequest
  {
   string schema_version;
   string request_id;
   string action;
   string idempotency_key;
   string auth_tag;
   // chart_selector fields
   long   chart_id;        // -1 = not provided
   string symbol;
   string timeframe;
   // object fields (create / update / delete)
   string object_name;
   string object_type;
   string properties_json; // raw sub-string extracted from the JSON
   string points_json;     // raw sub-string extracted from the JSON
  };

//+------------------------------------------------------------------+
//| Response builders                                                |
//+------------------------------------------------------------------+

string BuildErrorResponse(
   const string request_id,
   const string action,
   const string code,
   const string message
)
  {
   string safe_msg = message;
   StringReplace(safe_msg, "\"", "'");   // avoid breaking JSON string
   return StringFormat(
      "{\"request_id\":\"%s\",\"action\":\"%s\",\"status\":\"error\","
      "\"verified\":false,\"error_code\":\"%s\",\"error_message\":\"%s\"}",
      request_id, action, code, safe_msg
   );
  }

string BuildChartsResponse(const string request_id, const string charts_json)
  {
   return StringFormat(
      "{\"request_id\":\"%s\",\"action\":\"list_charts\",\"status\":\"ok\","
      "\"verified\":true,\"charts\":%s}",
      request_id, charts_json
   );
  }

string BuildAckResponse(
   const string request_id,
   const string action,
   const bool   verified,
   const string observed_properties_json,
   const string error_code    = "",
   const string error_message = ""
)
  {
   string status = verified ? "ok" : "error";
   string safe_ec  = error_code;
   string safe_em  = error_message;
   StringReplace(safe_em, "\"", "'");
   return StringFormat(
      "{\"request_id\":\"%s\",\"action\":\"%s\",\"status\":\"%s\","
      "\"verified\":%s,\"error_code\":\"%s\",\"error_message\":\"%s\","
      "\"observed_properties\":%s}",
      request_id, action, status,
      verified ? "true" : "false",
      safe_ec, safe_em,
      observed_properties_json
   );
  }

string BuildClearResponse(const string request_id, const int deleted_count)
  {
   return StringFormat(
      "{\"request_id\":\"%s\",\"action\":\"clear_objects\",\"status\":\"ok\","
      "\"verified\":true,\"deleted_count\":%d,\"observed_properties\":{}}",
      request_id, deleted_count
   );
  }

//+------------------------------------------------------------------+
//| HMAC-SHA256 helpers                                              |
//+------------------------------------------------------------------+

// Convert a string to a uchar[] using UTF-8 encoding, WITHOUT the
// trailing NUL byte that StringToCharArray appends by default.
// IMPORTANT: This is the #1 byte-mismatch trap.  The count argument
// StringLen(s) stops BEFORE the NUL so we get clean UTF-8 bytes only.
void StringToUtf8Bytes(const string s, uchar &out[])
  {
   int n = StringLen(s);
   if(n == 0)
     {
      ArrayResize(out, 0);
      return;
     }
   // Allocate generously (UTF-8 can be up to 4 bytes per codepoint)
   ArrayResize(out, n * 4);
   int written = StringToCharArray(s, out, 0, n, CP_UTF8);
   ArrayResize(out, written);
  }

// SHA-256 of a byte array using CryptEncode.
// Returns the 32-byte raw digest in 'digest'.
bool Sha256Raw(const uchar &data[], uchar &digest[])
  {
   uchar key_dummy[];   // CryptEncode ignores the key param for HASH modes
   ArrayResize(key_dummy, 0);
   uchar tmp[];
   if(!CryptEncode(CRYPT_HASH_SHA256, data, key_dummy, tmp))
      return false;
   ArrayCopy(digest, tmp);
   return true;
  }

// XOR a 64-byte key block with a constant pad byte.
void XorBlock(const uchar &block_in[], uchar &block_out[], const uchar pad)
  {
   ArrayResize(block_out, HMAC_BLOCK_SIZE);
   for(int i = 0; i < HMAC_BLOCK_SIZE; i++)
      block_out[i] = block_in[i] ^ pad;
  }

// HMAC-SHA256(key_str, message_str) → lowercase hex string (64 chars).
// Implements the standard HMAC construction:
//   K' = key if len<=64 else SHA256(key), right-padded to 64 bytes with 0x00
//   inner = SHA256((K' XOR ipad) || message)
//   outer = SHA256((K' XOR opad) || inner)
//   tag   = lowercase_hex(outer)
string HmacSha256(const string key_str, const string message_str)
  {
   // ── 1. Prepare key bytes ────────────────────────────────────────
   uchar key_bytes[];
   StringToUtf8Bytes(key_str, key_bytes);

   uchar k_prime[];
   ArrayResize(k_prime, HMAC_BLOCK_SIZE);
   ArrayInitialize(k_prime, 0);

   int key_len = ArraySize(key_bytes);
   if(key_len > HMAC_BLOCK_SIZE)
     {
      // K' = SHA256(key)
      uchar hashed_key[];
      if(!Sha256Raw(key_bytes, hashed_key))
         return "";
      int copy_len = MathMin(ArraySize(hashed_key), HMAC_BLOCK_SIZE);
      ArrayCopy(k_prime, hashed_key, 0, 0, copy_len);
     }
   else
     {
      ArrayCopy(k_prime, key_bytes, 0, 0, key_len);
      // Rest already 0x00-padded by ArrayInitialize
     }

   // ── 2. Inner hash: SHA256((K' XOR ipad) || message) ───────────
   uchar ipad_block[];
   XorBlock(k_prime, ipad_block, 0x36);

   uchar msg_bytes[];
   StringToUtf8Bytes(message_str, msg_bytes);

   uchar inner_input[];
   int ipad_len = ArraySize(ipad_block);
   int msg_len  = ArraySize(msg_bytes);
   ArrayResize(inner_input, ipad_len + msg_len);
   ArrayCopy(inner_input, ipad_block, 0, 0, ipad_len);
   ArrayCopy(inner_input, msg_bytes,  ipad_len, 0, msg_len);

   uchar inner_hash[];
   if(!Sha256Raw(inner_input, inner_hash))
      return "";

   // ── 3. Outer hash: SHA256((K' XOR opad) || inner) ─────────────
   uchar opad_block[];
   XorBlock(k_prime, opad_block, 0x5C);

   uchar outer_input[];
   int opad_len  = ArraySize(opad_block);
   int inner_len = ArraySize(inner_hash);
   ArrayResize(outer_input, opad_len + inner_len);
   ArrayCopy(outer_input, opad_block, 0, 0, opad_len);
   ArrayCopy(outer_input, inner_hash, opad_len, 0, inner_len);

   uchar outer_hash[];
   if(!Sha256Raw(outer_input, outer_hash))
      return "";

   // ── 4. Lowercase hex (no separators, 64 chars) ────────────────
   string hex = "";
   int digest_len = ArraySize(outer_hash);
   for(int i = 0; i < digest_len; i++)
     {
      string byte_hex = StringFormat("%02x", (int)outer_hash[i]);
      hex += byte_hex;
     }
   return hex;
  }

// Verify the auth_tag on a request.  Computes HMAC over the canonical
// message field (schema_version:request_id:action:idempotency_key) and
// does a constant-time-ish string comparison.
//
// Returns false and sets error_code to "auth_failed" on mismatch.
bool VerifyAuthTag(const ChartBridgeRequest &request)
  {
   if(StringLen(SharedSecret) == 0)
      return false;  // no secret configured — reject everything
   if(StringLen(request.auth_tag) != 64)
      return false;  // wrong length is an immediate reject

   string message = request.schema_version + ":" + request.request_id + ":" +
                    request.action + ":" + request.idempotency_key;
   string computed = HmacSha256(SharedSecret, message);
   if(StringLen(computed) != 64)
      return false;

   // Constant-time-ish compare: compare all 64 chars, accumulate diff
   int diff = 0;
   for(int i = 0; i < 64; i++)
      diff |= (StringGetCharacter(computed, i) != StringGetCharacter(request.auth_tag, i)) ? 1 : 0;
   return diff == 0;
  }

//+------------------------------------------------------------------+
//| Chart resolution                                                 |
//+------------------------------------------------------------------+

bool ResolveChart(const ChartBridgeRequest &request, long &chart_id)
  {
   // Priority: explicit chart_id > symbol > symbol+timeframe
   if(request.chart_id > 0)
     {
      chart_id = request.chart_id;
      // Validate it actually exists
      long c = ChartFirst();
      while(c >= 0)
        {
         if(c == request.chart_id) { return true; }
         c = ChartNext(c);
        }
      return false;
     }

   long current = ChartFirst();
   while(current >= 0)
     {
      // Case-insensitive match. StringToUpper modifies a string IN PLACE and
      // returns bool, and request.* are const (cannot be passed by reference),
      // so uppercase mutable local copies and compare those.
      string chart_symbol = ChartSymbol(current);
      StringToUpper(chart_symbol);
      string req_symbol = request.symbol;
      StringToUpper(req_symbol);
      bool symbol_match = (request.symbol == "") || (chart_symbol == req_symbol);
      bool tf_match = true;
      if(request.timeframe != "")
        {
         string chart_tf = EnumToString((ENUM_TIMEFRAMES)ChartPeriod(current));
         StringToUpper(chart_tf);
         string req_tf = request.timeframe;
         StringToUpper(req_tf);
         tf_match = (chart_tf == req_tf);
        }
      if(symbol_match && tf_match)
        {
         chart_id = current;
         return true;
        }
      current = ChartNext(current);
     }
   return false;
  }

string EnumerateChartsJson()
  {
   string items = "[";
   bool   first = true;
   long   chart_id = ChartFirst();
   while(chart_id >= 0)
     {
      string item = StringFormat(
         "{\"chart_id\":%I64d,\"symbol\":\"%s\",\"timeframe\":\"%s\"}",
         chart_id,
         ChartSymbol(chart_id),
         EnumToString((ENUM_TIMEFRAMES)ChartPeriod(chart_id))
      );
      if(!first) items += ",";
      items += item;
      first = false;
      chart_id = ChartNext(chart_id);
     }
   items += "]";
   return items;
  }

//+------------------------------------------------------------------+
//| Minimal hand-rolled JSON field extractor                         |
//|                                                                  |
//| We extract simple scalar and object/array values from the        |
//| request JSON without an external library.  Strings are unescaped |
//| only for simple cases (no Unicode escape sequences expected in   |
//| field names and most values).                                    |
//+------------------------------------------------------------------+

// Extract a JSON string value for the given key.
// Returns "" when the key is absent or value is not a string.
string JsonGetString(const string json, const string key)
  {
   string search = "\"" + key + "\":\"";
   int start = StringFind(json, search);
   if(start < 0) return "";
   start += StringLen(search);
   int end = StringFind(json, "\"", start);
   if(end < 0) return "";
   return StringSubstr(json, start, end - start);
  }

// Extract a JSON integer/long value for the given key.
// Returns def_val when the key is absent or value is not a number.
long JsonGetLong(const string json, const string key, const long def_val = -1)
  {
   string search = "\"" + key + "\":";
   int start = StringFind(json, search);
   if(start < 0) return def_val;
   start += StringLen(search);
   // Skip whitespace
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ') start++;
   // Read digits
   string num_str = "";
   while(start < StringLen(json))
     {
      ushort ch = StringGetCharacter(json, start);
      if(ch >= '0' && ch <= '9')
        {
         num_str += ShortToString(ch);
         start++;
        }
      else
         break;
     }
   if(StringLen(num_str) == 0) return def_val;
   return (long)StringToInteger(num_str);
  }

// Extract a JSON double value for the given key.
// Returns def_val when absent.
double JsonGetDouble(const string json, const string key, const double def_val = 0.0)
  {
   string search = "\"" + key + "\":";
   int start = StringFind(json, search);
   if(start < 0) return def_val;
   start += StringLen(search);
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ') start++;
   string num_str = "";
   while(start < StringLen(json))
     {
      ushort ch = StringGetCharacter(json, start);
      if((ch >= '0' && ch <= '9') || ch == '.' || ch == '-' || ch == 'e' || ch == 'E' || ch == '+')
        {
         num_str += ShortToString(ch);
         start++;
        }
      else
         break;
     }
   if(StringLen(num_str) == 0) return def_val;
   return StringToDouble(num_str);
  }

// Check whether a JSON boolean value is true for the given key.
bool JsonGetBool(const string json, const string key, const bool def_val = false)
  {
   string search = "\"" + key + "\":";
   int start = StringFind(json, search);
   if(start < 0) return def_val;
   start += StringLen(search);
   while(start < StringLen(json) && StringGetCharacter(json, start) == ' ') start++;
   if(StringFind(json, "true", start) == start)  return true;
   if(StringFind(json, "false", start) == start) return false;
   return def_val;
  }

// Extract the raw substring for a JSON object/array value.
// Handles nested braces/brackets.  Returns "" when not found.
string JsonGetRaw(const string json, const string key)
  {
   string search = "\"" + key + "\":";
   int pos = StringFind(json, search);
   if(pos < 0) return "";
   pos += StringLen(search);
   // Skip whitespace
   while(pos < StringLen(json) && StringGetCharacter(json, pos) == ' ') pos++;
   if(pos >= StringLen(json)) return "";
   ushort open_ch = StringGetCharacter(json, pos);
   ushort close_ch;
   if(open_ch == '{')      close_ch = '}';
   else if(open_ch == '[') close_ch = ']';
   else                    return "";  // not an object/array
   int depth = 0;
   int start = pos;
   while(pos < StringLen(json))
     {
      ushort ch = StringGetCharacter(json, pos);
      if(ch == open_ch)  depth++;
      if(ch == close_ch) { depth--; if(depth == 0) { pos++; break; } }
      // Skip over JSON strings to avoid counting braces inside them
      if(ch == '"')
        {
         pos++;
         while(pos < StringLen(json))
           {
            ushort sc = StringGetCharacter(json, pos);
            pos++;
            if(sc == '"')  break;
            if(sc == '\\') pos++;  // skip escaped char
           }
         continue;
        }
      pos++;
     }
   return StringSubstr(json, start, pos - start);
  }

// Parse the top-level request JSON into a ChartBridgeRequest struct.
bool ParseRequest(const string json, ChartBridgeRequest &req)
  {
   req.schema_version  = JsonGetString(json, "schema_version");
   req.request_id      = JsonGetString(json, "request_id");
   req.action          = JsonGetString(json, "action");
   req.idempotency_key = JsonGetString(json, "idempotency_key");
   req.auth_tag        = JsonGetString(json, "auth_tag");

   // chart_selector sub-object
   string sel = JsonGetRaw(json, "chart_selector");
   if(StringLen(sel) > 0)
     {
      req.chart_id  = JsonGetLong(sel, "chart_id", -1);
      req.symbol    = JsonGetString(sel, "symbol");
      req.timeframe = JsonGetString(sel, "timeframe");
     }
   else
     {
      req.chart_id  = -1;
      req.symbol    = "";
      req.timeframe = "";
     }

   // object sub-object
   string obj = JsonGetRaw(json, "object");
   if(StringLen(obj) > 0)
     {
      req.object_name    = JsonGetString(obj, "name");
      req.object_type    = JsonGetString(obj, "object_type");
      req.properties_json = JsonGetRaw(obj, "properties");
      req.points_json    = JsonGetRaw(obj, "points");
     }
   else
     {
      req.object_name    = "";
      req.object_type    = "";
      req.properties_json = "";
      req.points_json    = "";
     }

   return StringLen(req.request_id) > 0 && StringLen(req.action) > 0;
  }

//+------------------------------------------------------------------+
//| Object-type mapping                                              |
//+------------------------------------------------------------------+

ENUM_OBJECT ResolveObjectType(const string type_str)
  {
   string upper = type_str;
   StringToUpper(upper);
   if(upper == "HLINE")                         return OBJ_HLINE;
   if(upper == "VLINE")                         return OBJ_VLINE;
   if(upper == "TREND" || upper == "TRENDLINE") return OBJ_TREND;
   if(upper == "RECTANGLE" || upper == "RECT")  return OBJ_RECTANGLE;
   if(upper == "TEXT")                          return OBJ_TEXT;
   if(upper == "ARROW")                         return OBJ_ARROW;
   if(upper == "LABEL")                         return OBJ_LABEL;
   if(upper == "CHANNEL")                       return OBJ_CHANNEL;
   if(upper == "REGRESSION")                    return OBJ_REGRESSION;
   if(upper == "STDDEVCHANNEL")                 return OBJ_STDDEVCHANNEL;
   if(upper == "PITCHFORK")                     return OBJ_PITCHFORK;
   if(upper == "GANNLINE")                      return OBJ_GANNLINE;
   if(upper == "GANNGRID")                      return OBJ_GANNGRID;
   if(upper == "GANNFAN")                       return OBJ_GANNFAN;
   if(upper == "FIBO")                          return OBJ_FIBO;
   if(upper == "FIBOTIMES")                     return OBJ_FIBOTIMES;
   if(upper == "FIBOFAN")                       return OBJ_FIBOFAN;
   if(upper == "FIBOARC")                       return OBJ_FIBOARC;
   if(upper == "FIBOCHANNEL")                   return OBJ_FIBOCHANNEL;
   if(upper == "EXPANSION")                     return OBJ_EXPANSION;
   if(upper == "ELLIOTWAVE5")                   return OBJ_ELLIOTWAVE5;
   if(upper == "ELLIOTWAVE3")                   return OBJ_ELLIOTWAVE3;
   if(upper == "CYCLES")                        return OBJ_CYCLES;
   return (ENUM_OBJECT)(-1);  // unsupported
  }

// Expected point count for the given object type (-1 = any).
int ExpectedPointCount(const ENUM_OBJECT obj_type)
  {
   switch(obj_type)
     {
      case OBJ_HLINE:       return 1;
      case OBJ_VLINE:       return 1;
      case OBJ_TEXT:        return 1;
      case OBJ_ARROW:       return 1;
      case OBJ_LABEL:       return 1;
      case OBJ_TREND:       return 2;
      case OBJ_RECTANGLE:   return 2;
      case OBJ_CHANNEL:     return 2;
      case OBJ_REGRESSION:  return 2;
      default:              return -1;  // any (handled by ObjectCreate default)
     }
  }

//+------------------------------------------------------------------+
//| Color string → clrXxx mapping                                   |
//+------------------------------------------------------------------+

color MapColorName(const string color_str)
  {
   string lower = color_str;
   StringToLower(lower);
   if(lower == "red")       return clrRed;
   if(lower == "green")     return clrGreen;
   if(lower == "blue")      return clrBlue;
   if(lower == "yellow")    return clrYellow;
   if(lower == "orange")    return clrOrange;
   if(lower == "purple")    return clrPurple;
   if(lower == "white")     return clrWhite;
   if(lower == "black")     return clrBlack;
   if(lower == "gray" || lower == "grey") return clrGray;
   if(lower == "lime")      return clrLime;
   if(lower == "aqua" || lower == "cyan") return clrAqua;
   if(lower == "magenta" || lower == "fuchsia") return clrMagenta;
   if(lower == "silver")    return clrSilver;
   if(lower == "navy")      return clrNavy;
   if(lower == "teal")      return clrTeal;
   if(lower == "maroon")    return clrMaroon;
   if(lower == "olive")     return clrOlive;
   if(lower == "coral")     return clrCoral;
   if(lower == "gold")      return clrGold;
   if(lower == "salmon")    return clrSalmon;
   if(lower == "pink")      return clrPink;
   if(lower == "violet")    return clrViolet;
   if(lower == "indigo")    return clrIndigo;
   if(lower == "crimson")   return clrCrimson;
   if(lower == "chocolate") return clrChocolate;
   if(lower == "tomato")    return clrTomato;
   if(lower == "khaki")     return clrKhaki;
   // Fallback: try integer
   long int_val = StringToInteger(color_str);
   if(int_val > 0 || color_str == "0")
      return (color)int_val;
   return clrNONE;
  }

// Line style string → ENUM_LINE_STYLE
ENUM_LINE_STYLE MapLineStyle(const string style_str)
  {
   string lower = style_str;
   StringToLower(lower);
   if(lower == "solid")     return STYLE_SOLID;
   if(lower == "dash")      return STYLE_DASH;
   if(lower == "dot")       return STYLE_DOT;
   if(lower == "dashdot")   return STYLE_DASHDOT;
   if(lower == "dashdotdot") return STYLE_DASHDOTDOT;
   return STYLE_SOLID;  // default
  }

//+------------------------------------------------------------------+
//| Points JSON parser                                               |
//| Parses the array returned by JsonGetRaw(json, "points").        |
//| Returns the number of points parsed (up to max_points).         |
//+------------------------------------------------------------------+

struct ChartPoint
  {
   bool     has_time;
   datetime time_val;
   bool     has_price;
   double   price_val;
   bool     has_index;
   int      index_val;
  };

int ParsePoints(
   const string  points_json,
   const long    chart_id,
   const string  symbol,
   ChartPoint   &pts[],
   const int     max_points
)
  {
   if(StringLen(points_json) < 2) return 0;  // empty or missing
   // points_json is a JSON array: [{...},{...},...]
   // We scan for '{' to find each element.
   int count = 0;
   int pos   = 0;
   int json_len = StringLen(points_json);

   while(pos < json_len && count < max_points)
     {
      // Find next '{'
      int obj_start = StringFind(points_json, "{", pos);
      if(obj_start < 0) break;
      // Find matching '}'
      int depth = 0;
      int obj_end = obj_start;
      while(obj_end < json_len)
        {
         ushort ch = StringGetCharacter(points_json, obj_end);
         if(ch == '{') depth++;
         if(ch == '}') { depth--; if(depth == 0) { obj_end++; break; } }
         if(ch == '"')
           {
            obj_end++;
            while(obj_end < json_len)
              {
               ushort sc = StringGetCharacter(points_json, obj_end);
               obj_end++;
               if(sc == '"')  break;
               if(sc == '\\') obj_end++;
              }
            continue;
           }
         obj_end++;
        }
      string elem = StringSubstr(points_json, obj_start, obj_end - obj_start);

      ChartPoint pt;
      pt.has_time  = false;
      pt.has_price = false;
      pt.has_index = false;
      pt.time_val  = 0;
      pt.price_val = 0.0;
      pt.index_val = 0;

      // time field (ISO-8601 string → StringToTime)
      string time_str = JsonGetString(elem, "time");
      if(StringLen(time_str) > 0)
        {
         // StringToTime accepts "YYYY.MM.DD HH:MM:SS" and ISO variants.
         // Replace T separator for compatibility.
         StringReplace(time_str, "T", " ");
         StringReplace(time_str, "Z", "");
         // Strip +00:00 offset suffix if present
         int plus_pos = StringFind(time_str, "+");
         if(plus_pos > 0) time_str = StringSubstr(time_str, 0, plus_pos);
         pt.time_val = StringToTime(time_str);
         pt.has_time = true;
        }

      // price field
      string price_key_search = "\"price\":";
      if(StringFind(elem, price_key_search) >= 0)
        {
         pt.price_val = JsonGetDouble(elem, "price", 0.0);
         pt.has_price = true;
        }

      // index field → resolve to time via iTime
      string index_key_search = "\"index\":";
      if(StringFind(elem, index_key_search) >= 0)
        {
         int bar_idx = (int)JsonGetLong(elem, "index", -1);
         if(bar_idx >= 0)
           {
            string sym_use = StringLen(symbol) > 0 ? symbol : ChartSymbol(chart_id);
            ENUM_TIMEFRAMES tf = (ENUM_TIMEFRAMES)ChartPeriod(chart_id);
            pt.time_val = iTime(sym_use, tf, bar_idx);
            pt.has_time = (pt.time_val > 0);
            pt.index_val = bar_idx;
            pt.has_index = true;
           }
        }

      pts[count] = pt;
      count++;
      pos = obj_end;
     }
   return count;
  }

//+------------------------------------------------------------------+
//| Apply properties to an existing object                           |
//+------------------------------------------------------------------+

void ApplyProperties(
   const long    chart_id,
   const string  obj_name,
   const string  properties_json
)
  {
   if(StringLen(properties_json) < 2) return;

   // color
   string color_str = JsonGetString(properties_json, "color");
   if(StringLen(color_str) > 0)
     {
      color clr = MapColorName(color_str);
      if(clr != clrNONE)
         ObjectSetInteger(chart_id, obj_name, OBJPROP_COLOR, clr);
     }

   // style
   string style_str = JsonGetString(properties_json, "style");
   if(StringLen(style_str) > 0)
     {
      ENUM_LINE_STYLE ls = MapLineStyle(style_str);
      ObjectSetInteger(chart_id, obj_name, OBJPROP_STYLE, ls);
     }

   // width
   string width_key_search = "\"width\":";
   if(StringFind(properties_json, width_key_search) >= 0)
     {
      long w = JsonGetLong(properties_json, "width", -1);
      if(w >= 1 && w <= 5)
         ObjectSetInteger(chart_id, obj_name, OBJPROP_WIDTH, w);
     }

   // text (for OBJ_TEXT, OBJ_LABEL, etc.)
   string text_str = JsonGetString(properties_json, "text");
   if(StringLen(text_str) > 0)
      ObjectSetString(chart_id, obj_name, OBJPROP_TEXT, text_str);

   // description (stored as tooltip/name suffix — use OBJPROP_TOOLTIP)
   string desc_str = JsonGetString(properties_json, "description");
   if(StringLen(desc_str) > 0)
      ObjectSetString(chart_id, obj_name, OBJPROP_TOOLTIP, desc_str);

   // fontsize (for text objects)
   string fontsize_key_search = "\"fontsize\":";
   if(StringFind(properties_json, fontsize_key_search) >= 0)
     {
      long fs = JsonGetLong(properties_json, "fontsize", -1);
      if(fs > 0)
         ObjectSetInteger(chart_id, obj_name, OBJPROP_FONTSIZE, fs);
     }

   // fill (bool, for rectangles etc.)
   string fill_key_search = "\"fill\":";
   if(StringFind(properties_json, fill_key_search) >= 0)
     {
      bool fill_val = JsonGetBool(properties_json, "fill", false);
      ObjectSetInteger(chart_id, obj_name, OBJPROP_FILL, fill_val ? 1 : 0);
     }

   // ray_right (bool, for trend lines)
   string ray_key_search = "\"ray_right\":";
   if(StringFind(properties_json, ray_key_search) >= 0)
     {
      bool ray_val = JsonGetBool(properties_json, "ray_right", false);
      ObjectSetInteger(chart_id, obj_name, OBJPROP_RAY_RIGHT, ray_val ? 1 : 0);
     }
  }

//+------------------------------------------------------------------+
//| Object coordinate setter                                         |
//| Sets time/price for point index pt_idx (0-based).               |
//+------------------------------------------------------------------+

void SetObjectPoint(
   const long        chart_id,
   const string      obj_name,
   const int         pt_idx,
   const ChartPoint &pt
)
  {
   if(pt.has_time)
      ObjectSetInteger(chart_id, obj_name, OBJPROP_TIME,  pt_idx, pt.time_val);
   if(pt.has_price)
      ObjectSetDouble(chart_id,  obj_name, OBJPROP_PRICE, pt_idx, pt.price_val);
  }

//+------------------------------------------------------------------+
//| Create object handler                                            |
//+------------------------------------------------------------------+

bool ApplyCreateObject(
   const long               chart_id,
   const ChartBridgeRequest &request,
   string                   &observed_json
)
  {
   ENUM_OBJECT obj_type = ResolveObjectType(request.object_type);
   if(obj_type == (ENUM_OBJECT)(-1))
     {
      observed_json = "{}";
      return false;  // caller must emit unsupported_object_type
     }

   // Parse points
   ChartPoint pts[];
   ArrayResize(pts, 8);  // max 8 points for exotic objects
   int pt_count = ParsePoints(
      request.points_json, chart_id, request.symbol, pts, 8
   );

   // Validate point count
   int expected = ExpectedPointCount(obj_type);
   if(expected > 0 && pt_count < expected)
     {
      observed_json = "{}";
      return false;  // caller will emit verify_failed
     }

   // Use a safe default time/price when points have only price (HLINE) or only time (VLINE)
   datetime t0 = (pt_count > 0 && pts[0].has_time)  ? pts[0].time_val  : TimeCurrent();
   double   p0 = (pt_count > 0 && pts[0].has_price) ? pts[0].price_val :
                  SymbolInfoDouble(ChartSymbol(chart_id), SYMBOL_BID);

   datetime t1 = (pt_count > 1 && pts[1].has_time)  ? pts[1].time_val  : TimeCurrent();
   double   p1 = (pt_count > 1 && pts[1].has_price) ? pts[1].price_val : p0;

   // Delete any pre-existing object with the same name (idempotency)
   if(ObjectFind(chart_id, request.object_name) >= 0)
      ObjectDelete(chart_id, request.object_name);

   bool created = ObjectCreate(chart_id, request.object_name, obj_type, 0, t0, p0);
   if(!created)
     {
      observed_json = StringFormat(
         "{\"name\":\"%s\",\"error\":\"%s\",\"last_error\":%d}",
         request.object_name,
         "ObjectCreate failed",
         GetLastError()
      );
      return false;
     }

   // Multi-anchor objects (RECTANGLE, TREND, CHANNEL...) need DISTINCT times on
   // each corner. Price-only requests like draw_zone supply no time, so every
   // corner would land on the same time → the object collapses to a vertical
   // line. Synthesise spanning times (staggered bars back from now) for any
   // secondary point that lacks one, giving the object real horizontal width.
   int bar_seconds = PeriodSeconds((ENUM_TIMEFRAMES)ChartPeriod(chart_id));
   for(int i = 1; i < pt_count; i++)
     {
      if(!pts[i].has_time)
        {
         pts[i].time_val = TimeCurrent() - (datetime)(i * 60 * bar_seconds);  // i*60 bars back
         pts[i].has_time = true;
        }
     }

   // Set additional points for multi-point objects
   if(pt_count > 1)
      SetObjectPoint(chart_id, request.object_name, 1, pts[1]);
   if(pt_count > 2)
      SetObjectPoint(chart_id, request.object_name, 2, pts[2]);

   // Apply properties
   ApplyProperties(chart_id, request.object_name, request.properties_json);

   ChartRedraw(chart_id);

   bool exists = ObjectFind(chart_id, request.object_name) >= 0;
   string color_out = "";
   if(exists)
     {
      long clr_val = ObjectGetInteger(chart_id, request.object_name, OBJPROP_COLOR);
      color_out = StringFormat("%d", clr_val);
     }
   observed_json = StringFormat(
      "{\"name\":\"%s\",\"object_type\":\"%s\",\"color\":%s}",
      request.object_name,
      request.object_type,
      StringLen(color_out) > 0 ? ("\"" + color_out + "\"") : "null"
   );
   return exists;
  }

//+------------------------------------------------------------------+
//| Update object handler                                            |
//+------------------------------------------------------------------+

bool ApplyUpdateObject(
   const long               chart_id,
   const ChartBridgeRequest &request,
   string                   &observed_json
)
  {
   if(ObjectFind(chart_id, request.object_name) < 0)
     {
      observed_json = StringFormat("{\"name\":\"%s\",\"exists\":false}", request.object_name);
      return false;
     }

   // Re-apply points if provided
   ChartPoint pts[];
   ArrayResize(pts, 8);
   int pt_count = ParsePoints(
      request.points_json, chart_id, request.symbol, pts, 8
   );
   for(int i = 0; i < pt_count; i++)
      SetObjectPoint(chart_id, request.object_name, i, pts[i]);

   // Re-apply properties
   ApplyProperties(chart_id, request.object_name, request.properties_json);

   ChartRedraw(chart_id);

   bool exists = ObjectFind(chart_id, request.object_name) >= 0;
   observed_json = StringFormat(
      "{\"name\":\"%s\",\"updated\":true,\"exists\":%s}",
      request.object_name,
      exists ? "true" : "false"
   );
   return exists;
  }

//+------------------------------------------------------------------+
//| Delete object handler                                            |
//+------------------------------------------------------------------+

bool ApplyDeleteObject(
   const long               chart_id,
   const ChartBridgeRequest &request,
   string                   &observed_json
)
  {
   bool deleted = ObjectDelete(chart_id, request.object_name);
   bool missing = ObjectFind(chart_id, request.object_name) < 0;
   ChartRedraw(chart_id);
   observed_json = StringFormat(
      "{\"name\":\"%s\",\"deleted\":%s}",
      request.object_name,
      (deleted && missing) ? "true" : "false"
   );
   return deleted && missing;
  }

//+------------------------------------------------------------------+
//| Clear-by-prefix handler (action = "clear_objects")              |
//| Deletes all objects on chart_id whose name starts with          |
//| YUGEN_PREFIX ("yugen_").  If chart_id == -1, iterates all open  |
//| charts.  Returns the total count of deleted objects.            |
//+------------------------------------------------------------------+

int ClearObjectsByPrefix(const long chart_id, const string prefix)
  {
   int deleted = 0;
   // Iterate backwards to avoid index-shift after delete
   int total = ObjectsTotal(chart_id, -1, -1);
   for(int i = total - 1; i >= 0; i--)
     {
      string obj_name = ObjectName(chart_id, i, -1, -1);
      if(StringFind(obj_name, prefix, 0) == 0)
        {
         if(ObjectDelete(chart_id, obj_name))
            deleted++;
        }
     }
   return deleted;
  }

string HandleClearObjects(const ChartBridgeRequest &request)
  {
   int total_deleted = 0;
   // If a chart_selector with symbol is provided, resolve to one chart.
   // If selector resolves, clear only that chart.
   // If no selector (chart_id == -1 and symbol == ""), clear all charts.
   if(request.chart_id > 0 || StringLen(request.symbol) > 0)
     {
      long chart_id = -1;
      if(!ResolveChart(request, chart_id))
         return BuildErrorResponse(request.request_id, request.action,
                                   "chart_not_found", "Unable to resolve chart target");
      total_deleted = ClearObjectsByPrefix(chart_id, YUGEN_PREFIX);
      ChartRedraw(chart_id);
     }
   else
     {
      // No selector → clear all open charts
      long c = ChartFirst();
      while(c >= 0)
        {
         total_deleted += ClearObjectsByPrefix(c, YUGEN_PREFIX);
         ChartRedraw(c);
         c = ChartNext(c);
        }
     }
   return BuildClearResponse(request.request_id, total_deleted);
  }

//+------------------------------------------------------------------+
//| Main dispatch                                                    |
//+------------------------------------------------------------------+

string HandleRequest(const ChartBridgeRequest &request)
  {
   // ── schema version gate ────────────────────────────────────────
   if(request.schema_version != SCHEMA_VERSION)
      return BuildErrorResponse(request.request_id, request.action,
                                "schema_mismatch", "Unsupported schema version");

   // ── HMAC auth gate ─────────────────────────────────────────────
   if(!VerifyAuthTag(request))
      return BuildErrorResponse(request.request_id, request.action,
                                "auth_failed", "Auth tag verification failed");

   // ── list_charts (no chart resolution needed) ───────────────────
   if(request.action == "list_charts")
      return BuildChartsResponse(request.request_id, EnumerateChartsJson());

   // ── clear_objects (special: may operate on all charts) ─────────
   if(request.action == "clear_objects")
      return HandleClearObjects(request);

   // ── all other actions require chart resolution ─────────────────
   long chart_id = -1;
   if(!ResolveChart(request, chart_id))
      return BuildErrorResponse(request.request_id, request.action,
                                "chart_not_found", "Unable to resolve chart target");

   string observed_json = "{}";
   bool   verified      = false;
   string extra_code    = "";

   if(request.action == "create_object")
     {
      ENUM_OBJECT ot = ResolveObjectType(request.object_type);
      if(ot == (ENUM_OBJECT)(-1))
         return BuildErrorResponse(request.request_id, request.action,
                                   "unsupported_object_type",
                                   "Unknown object_type: " + request.object_type);
      verified = ApplyCreateObject(chart_id, request, observed_json);
     }
   else if(request.action == "update_object")
     {
      verified = ApplyUpdateObject(chart_id, request, observed_json);
     }
   else if(request.action == "delete_object")
     {
      verified = ApplyDeleteObject(chart_id, request, observed_json);
     }
   else
     {
      return BuildErrorResponse(request.request_id, request.action,
                                "unknown_action", "Unsupported action: " + request.action);
     }

   if(!verified)
      return BuildAckResponse(request.request_id, request.action,
                              false, observed_json, "verify_failed",
                              "Post-action verification failed");

   return BuildAckResponse(request.request_id, request.action, true, observed_json);
  }

//+------------------------------------------------------------------+
//| Pipe I/O helpers                                                 |
//+------------------------------------------------------------------+

// Read one newline-delimited JSON line from the pipe handle.
// Accumulates bytes until 0x0A (LF).  Returns the line without the
// trailing newline, or "" on read error.
string ReadJsonLine(const int handle)
  {
   // Read in bulk CHUNKS, not one byte per FileReadArray call. The previous
   // byte-at-a-time loop fell into Sleep(2) between bytes whenever a 1-byte
   // read returned 0; on Windows Sleep(2) rounds up to the ~15ms system timer
   // tick, so a ~500-byte request cost ~7.5s (measured: read latency was
   // linear at ~15ms/byte). Reading up to 4096 bytes per call drains all bytes
   // currently buffered in the pipe in one shot, so we only Sleep when a read
   // truly returns nothing. Latency drops from O(bytes * 15ms) to O(chunks).
   uchar  chunk[];
   ArrayResize(chunk, 4096);
   uchar  accum[];
   ArrayResize(accum, 0);
   int    acc_len = 0;
   uint   start_tick = GetTickCount();
   bool   found_lf = false;

   while(!IsStopped() && !found_lf)
     {
      uint read_count = FileReadArray(handle, chunk, 0, 4096);
      if(read_count == 0)
        {
         // Nothing available YET. Do NOT break on FileIsEnding here: on a
         // named pipe it can report end-of-file while Python is still
         // streaming the request, which truncates the line (the request_id
         // near the end of the sorted JSON gets cut → parse_error). Wait and
         // retry until the newline arrives, bounded by a safety deadline so a
         // genuinely dead peer cannot hang the service forever.
         if(GetTickCount() - start_tick > 5000)  // 5s no-progress deadline
            break;
         Sleep(2);
         continue;
        }
      start_tick = GetTickCount();  // made progress — reset the deadline
      for(uint i = 0; i < read_count; i++)
        {
         uchar byte_val = chunk[i];
         if(byte_val == 0x0A)  // LF = end of JSON line. Trailing bytes (if any)
           {                   // are ignored: protocol is one request per
            found_lf = true;   // connection, so nothing follows the newline.
            break;
           }
         ArrayResize(accum, acc_len + 1);
         accum[acc_len] = byte_val;
         acc_len++;
         if(acc_len > 65536)  // safety cap: 64 KB max request
           {
            found_lf = true;
            break;
           }
        }
     }

   if(acc_len == 0)
      return "";
   // CharArrayToString (not MQL4 CharToStr) with explicit CP_UTF8
   return CharArrayToString(accum, 0, acc_len, CP_UTF8);
  }

// Write a newline-terminated string to the pipe handle.
// Uses StringToCharArray with explicit count (no trailing NUL).
void WriteJsonLine(const int handle, const string response)
  {
   string line = response + "\n";
   uchar  out_buf[];
   int    n = StringLen(line);
   ArrayResize(out_buf, n * 4);  // generous for UTF-8
   int written = StringToCharArray(line, out_buf, 0, n, CP_UTF8);
   if(written > 0)
      FileWriteArray(handle, out_buf, 0, written);
   FileFlush(handle);
  }

//+------------------------------------------------------------------+
//| Service entry point                                              |
//| Runs the reconnecting pipe-client loop.                          |
//| One FileOpen per request, matching the Python connect-per-request|
//| server lifecycle (PipeTransport).                                |
//+------------------------------------------------------------------+

void OnStart()
  {
   if(StringLen(SharedSecret) == 0)
     {
      Print("YugenChartBridgeService: ERROR — SharedSecret input is empty. "
            "Set the SharedSecret input to the value of YUGEN_MT5_CHART_SHARED_SECRET. Stopping.");
      return;
     }

   string full_pipe = "\\\\.\\pipe\\" + PipeName;
   Print("YugenChartBridgeService: starting. Pipe=", full_pipe);

   while(!IsStopped())
     {
      // FileOpen on the named pipe — succeeds only when Python's
      // PipeTransport is inside an active exchange() call (server is
      // waiting for a client connection between ConnectNamedPipe and
      // the first ReadFile).
      int handle = FileOpen(
         full_pipe,
         FILE_READ | FILE_WRITE | FILE_BIN | FILE_ANSI
      );

      if(handle == INVALID_HANDLE)
        {
         // Server not yet ready (or between requests) — retry after a
         // short pause.  This is normal during startup and between requests.
         Sleep(50);
         continue;
        }

      // ── Connected for this request ─────────────────────────────
      string json_line = ReadJsonLine(handle);

      if(StringLen(json_line) == 0)
        {
         // Empty read — close and retry
         FileClose(handle);
         continue;
        }

      ChartBridgeRequest request;
      string response;
      if(!ParseRequest(json_line, request))
        {
         // Could not parse — reply with a generic error so Python
         // does not block waiting for the ACK.
         response = "{\"request_id\":\"unknown\",\"action\":\"unknown\","
                    "\"status\":\"error\",\"verified\":false,"
                    "\"error_code\":\"parse_error\","
                    "\"error_message\":\"Failed to parse request JSON\"}";
        }
      else
        {
         response = HandleRequest(request);
        }

      WriteJsonLine(handle, response);
      FileClose(handle);
      // Loop immediately — the next FileOpen will block until Python
      // arms the next exchange().
     }

   Print("YugenChartBridgeService: stopped.");
  }
