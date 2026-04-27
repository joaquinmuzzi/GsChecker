#!/bin/bash
echo "Testing GS-Checker API Endpoints"
echo "================================"
echo ""

ENDPOINTS=(
  "get_char/Lordaeron/Frodouwu"
  "get_char_talents/Lordaeron/Frodouwu"
  "get_guild_summary/Lordaeron/TestGuild/Frodouwu"
  "get_char_achievements/Lordaeron/Frodouwu"
  "get_char_statistics/Lordaeron/Frodouwu"
)

for i in "${!ENDPOINTS[@]}"; do
  endpoint="${ENDPOINTS[$i]}"
  echo "[$((i+1))] GET /$endpoint"
  echo "---"
  timeout 15 curl -k -s -w "\nHTTP Status: %{http_code}\n" "https://gs-checker.loca.lt/$endpoint" 2>&1 | head -c 400
  echo ""
  echo ""
done
