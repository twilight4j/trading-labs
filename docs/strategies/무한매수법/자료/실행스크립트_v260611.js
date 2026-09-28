/**
 * 무한매수법 V4 스크립트_1.1 (2026/06/11) - by 언이
 * 26/04/01 - 큰수 기준 추가, 후반전에서 별%/큰수 구분 시각화
 * 26/05/08 - 지정가 매도 후 LOC매수 로직 추가
 * 26/06/11 - 리버스 모드 진입 T >= n-1 -> T > n-1로 수정
 */

// ==========================================
// 0. 필수 보조 함수
// ==========================================
function getOrCreateDbSheet() {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let dbSheet = ss.getSheetByName("DB");
    
    if (!dbSheet) {
      dbSheet = ss.insertSheet("DB");
      const headers = ["날짜", "전략명", "모드", "종가($)", "평단가($)", "보유수량", "T값", "P값(⭐%)", "5일 평균(A)", "매입금액($)", "잔금($)", "1회 매수금($)", "실현손익($)", "매수주문", "매도 1 (쿼터)", "매도 2 (지정가)"];
      dbSheet.getRange("A1:P1").setValues([headers]);
      dbSheet.getRange("A1:P1").setFontWeight("bold").setBackground("#e0e0e0");
      dbSheet.setFrozenRows(1);
    }
    return dbSheet;
  }
  
  function getLastRecord(sheetName) {
    const dbSheet = getOrCreateDbSheet();
    const data = dbSheet.getDataRange().getValues();
    for (let i = data.length - 1; i >= 1; i--) {
      if (data[i][1] === sheetName) { 
        return { 
          oldShares: Number(data[i][5]) || 0, 
          oldAvgPrice: Number(data[i][4]) || 0,
          oldT: Number(data[i][6]) || 0,          // ★ DB에서 직전 T값(7번째 열)을 가져옴
          oldMode: String(data[i][2]) || "NORMAL" // ★ DB에서 직전 모드(3번째 열)를 가져옴
        }; 
      }
    }
    return { oldShares: 0, oldAvgPrice: 0, oldT: 0, oldMode: "NORMAL" };
  }
  
  function getOrCreateLogSheet() {
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    let logSheet = ss.getSheetByName("수익 일지");
    
    if (!logSheet) {
      logSheet = ss.insertSheet("수익 일지");
      const headers = ["종료 날짜", "종목", "시작 원금", "종료 금액", "수익금($)", "수익률(%)", "최종 T값"];
      logSheet.getRange("A1:G1").setValues([headers]);
      logSheet.getRange("A1:G1").setFontWeight("bold").setBackground("#d9ead3");
      logSheet.setFrozenRows(1);
    }
    return logSheet;
  }
  
  // ==========================================
  // 1. 사이클 시작 / 초기화
  // ==========================================
  function startCycle() {
    const sheet = SpreadsheetApp.getActiveSheet();
    const sheetName = sheet.getName();
    const ticker = String(sheet.getRange("B2").getValue() || "").toUpperCase();
    const n = Number(sheet.getRange("B3").getValue()) || 0;
    const principal = Number(sheet.getRange("B4").getValue()) || 0;
    const initialShares = Number(sheet.getRange("B6").getValue()) || 0;
    const initialAvgPrice = Number(sheet.getRange("B7").getValue()) || 0;
  
    // ★ D6 셀 값 불러오기 및 숫자 변환
    let rawStr = sheet.getRange("D6").getDisplayValue(); 
    let targetYield = parseFloat(rawStr.replace(/[^0-9.]/g, ""))
  
    // ★ 검증 (빈칸이거나 숫자가 아니거나 0 이하일 때 차단)
    if (!ticker || n <= 0 || principal <= 0 || isNaN(targetYield) || targetYield <= 0) {
      sheet.getRange("F2").setValue("⚠️ 오류: B2:B4(종목, 분할수, 원금)와 D6(목표수익률)를 정확히 입력하세요.");
      return;
    }
  
    if ((initialShares > 0 && initialAvgPrice <= 0) || (initialShares <= 0 && initialAvgPrice > 0)) {
      sheet.getRange("F2").setValue("⚠️ 입력 오류: 보유수량과 평단가 중 하나가 누락되었습니다!");
      return;
    }
  
    sheet.getRange("D2:D5").clearContent(); 
    sheet.getRange("D7").clearContent();
    sheet.getRange("F2:F6").clearContent();
    sheet.getRange("F3:F6").setValue("-");
  
    let balance = principal;
    let T = 0, P = 0, investedAmount = 0, amt = 0;
    let mode = "NORMAL";
  
    // ★ D6 셀의 값을 읽어옵니다.
    let startP = targetYield;
  
   if (initialShares > 0 && initialAvgPrice > 0) {
      investedAmount = initialShares * initialAvgPrice; 
      balance = principal - investedAmount;             
      T = (investedAmount / principal) * n; 
      P = startP - (startP / (n / 2)) * T; 
      if (T > n - 1) mode = "REVERSE";
      amt = (mode === "REVERSE") ? (balance / 4) : (balance / Math.max(0.1, n - T));
    } else {
      P = startP; balance = principal; amt = principal / n;
    }
  
    // 대시보드 출력 (% 서식 강제 고정)
    sheet.getRange("D2").setValue(mode); 
    sheet.getRange("D3").setValue(T.toFixed(5));
    sheet.getRange("D4").setValue(P / 100).setNumberFormat("0.00%"); 
    sheet.getRange("D5").setValue(balance.toFixed(2));
    sheet.getRange("D6").setValue(targetYield / 100).setNumberFormat("0.00%");
    
    updateVisuals(sheet, sheetName);
    
    const dbSheet = getOrCreateDbSheet();
    const today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
    
    dbSheet.appendRow([
      today, sheetName, mode, 0, initialAvgPrice.toFixed(2), initialShares, T.toFixed(5), P / 100, 0, 
      investedAmount.toFixed(2), balance.toFixed(2), amt.toFixed(2), "0.00", 
      initialShares > 0 ? "🚀 중간 진입 연결" : "🚀 새 사이클 시작", "-", "-"
    ]);
  
    dbSheet.getRange("H2:H").setNumberFormat("0.00%");
    
    sheet.getRange("F2").setValue(initialShares > 0 ? "✅ 중간 진입 연결 완료" : "✅ 새 사이클 시작 완료");
  }
  
  // ==========================================
  // 2. 일일 매수표 계산
  // ==========================================
  function updateDaily() {
    const sheet = SpreadsheetApp.getActiveSheet();
    const sheetName = sheet.getName();
    
    const ticker = String(sheet.getRange("B2").getValue() || "").toUpperCase();
    const n = Number(sheet.getRange("B3").getValue()) || 0;
    const principal = Number(sheet.getRange("B4").getValue()) || 0;
  
    // ★ D6 셀 값 불러오기 및 숫자 변환
    let rawStr = sheet.getRange("D6").getDisplayValue(); 
    let targetYield = parseFloat(rawStr.replace(/[^0-9.]/g, ""))
  
    // ★ B8 셀(큰수 기준) 값 추출 (빈칸이면 기본값 10%)
    let rawLargeStr = sheet.getRange("B8").getDisplayValue();
    let largeNumPct = parseFloat(rawLargeStr.replace(/[^0-9.]/g, "")) || 10; 
  
    const closePrice = Number(sheet.getRange("B5").getValue()) || 0;
    const newShares = Number(sheet.getRange("B6").getValue()) || 0;
    const newAvgPrice = Number(sheet.getRange("B7").getValue()) || 0;
    const sma5 = Number(sheet.getRange("D8").getValue()) || closePrice;
    
  if (!ticker || n <= 0 || closePrice <= 0 || isNaN(targetYield) || targetYield <= 0) {
      sheet.getRange("F2").setValue("⚠️ 오류: 설정값(B2:B4), 마감 종가(B5) 또는 목표수익률(D6)을 확인하세요.");
      return;
    }
  
    if ((newShares > 0 && newAvgPrice <= 0) || (newShares <= 0 && newAvgPrice > 0)) {
      sheet.getRange("F2").setValue("⚠️ 입력 오류: 보유수량과 평단가 중 하나가 누락되었습니다!");
      return; 
    }
  
    // ★ 수정된 코드: 대시보드를 무시하고 오직 DB의 마지막 기록만 믿고 시작함!
    const { oldShares, oldAvgPrice, oldT, oldMode } = getLastRecord(sheetName);
    
    let previousMode = oldMode; // DB에 기록된 진짜 직전 모드
    let mode = previousMode;
    let T = oldT;               // DB에 기록된 진짜 직전 T값
    
    let action = (newShares < oldShares) ? "SELL" : (newShares > oldShares) ? "BUY" : "NONE";
  
    // 매도/매수 시 T값 변동 및 손익 계산
    let todayProfit = 0;
  
   // ★ 매도/매수 상황 정밀 판별 (수량 변화폭 기준)
    if (action === "SELL") {
      let soldQty = oldShares - newShares;
      let qQty = Math.floor(oldShares * 0.25); // 1/4 쿼터 물량
      let limitSoldQty = oldShares - qQty;     // 3/4 지정가 물량
      
      if (newShares <= 0) {
        // [상황 1] 100% 매도 (사이클 종료)
        let limitPrice = oldAvgPrice * (1 + (targetYield / 100));
        let profitQ = qQty * (closePrice - oldAvgPrice);
        let profitLimit = limitSoldQty * (limitPrice - oldAvgPrice);
        todayProfit = profitQ + profitLimit;
      } 
      else if (newShares <= oldShares * 0.60) {
        // [상황 2] ★ 특수 상황: 3/4 지정가는 팔리고, 1/4는 남은 채로 LOC 매수까지 진행됨
        let limitPrice = oldAvgPrice * (1 + (targetYield / 100));
        todayProfit = limitSoldQty * (limitPrice - oldAvgPrice); // 3/4 지정가 매도 수익만 발생!
        
        if (newShares > qQty) { 
          // 남은 1/4 수량(qQty)보다 현재 수량이 많으면 무언가 새로 매수되었다는 뜻!
          if (closePrice > oldAvgPrice) {
            // 종가가 평단 위 ➔ 절반 매수만 체결됨
            T = (oldT * 0.25) + 0.5;
          } else {
            // 종가가 평단 아래 ➔ 전체 매수 체결됨
            T = (oldT * 0.25) + 1.0;
          }
        } else {
          // 혹시 매수도 체결 안 되고 딱 1/4 물량만 남은 경우
          T = oldT * 0.25; 
        }
      } 
      else {
        // [상황 3] 일반적인 1/4(쿼터) LOC 매도
        todayProfit = soldQty * (closePrice - oldAvgPrice);
        T = (mode === "NORMAL") ? oldT * 0.75 : oldT * (1 - (2 / n));
      }
    } else if (action === "BUY") {
      if (mode === "NORMAL") {
        if (oldShares === 0) {
          T = T + 1.0;
        } else if (T < n / 2) {
          if (closePrice > oldAvgPrice) T = T + 0.5; else T = T + 1.0;
        } else {
          T = T + 1.0;
        }
      } else if (mode === "REVERSE") {
        T = T + ((n - T) * 0.25);
      }
    }
  
    // 잔금 절대 계산
    const dbSheet = getOrCreateDbSheet();
    const dbData = dbSheet.getDataRange().getValues();
    let profitColIndex = (dbData[0] && dbData[0][2] === "모드") ? 12 : 11; 
    
    let totalPrevProfit = 0;
    for (let i = 1; i < dbData.length; i++) { 
      if (dbData[i][1] === sheetName) totalPrevProfit += Number(dbData[i][profitColIndex]) || 0; 
    }
    // 잔금 = 원금 - 현재 매입총액 + 과거 누적수익 + 오늘 발생한 자동 수익
    let balance = principal - (newShares * newAvgPrice) + totalPrevProfit + todayProfit;
  
    let startP = targetYield;
  
  // 모드 전환 판정 (★ 모드를 먼저 확정합니다)
    let isCycleEnd = (newShares <= 0 && action === "SELL");
    let finalT = oldT; // ★ 사이클이 0으로 초기화되기 전, 최종 T값을 따로 저장
  
    if (isCycleEnd) { 
      mode = "CYCLE_END"; 
      T = 0; 
    } else {
      if (mode === "NORMAL" && T > n - 1) mode = "REVERSE";
      else if (mode === "REVERSE" && closePrice > newAvgPrice * (1 - (targetYield / 100))) mode = "NORMAL";
    }
  
    // ★ 확정된 최종 모드를 바탕으로 P값을 계산
    let P = (mode === "NORMAL") ? (startP - (startP / (n / 2)) * T) : 0;
    
    // --------------------------------------------------
    // 주문서 생성
    // --------------------------------------------------
    let buyOrder = "-"; let sellOrder1 = "-"; let sellOrder2 = "-";
    let largeNum = closePrice * (1 + (largeNumPct / 100));
    let amt = 0; 
    
    if (!isCycleEnd) {
      let remT = Math.max(0.1, n - T); 
      amt = (mode === "REVERSE") ? (balance / 4) : (balance / remT);
      let baseQty = 0; 
  
      // ★ 매도용 원본 가격과 매수용(-0.01) 가격의 분리
      let targetPPrice = Math.max(0.01, newAvgPrice * (1 + (P / 100))); // 일반 매도용 (원본)
      let targetPBuyPrice = Math.max(0.01, targetPPrice - 0.01);        // 일반 매수용 (-0.01 차감)
      let sma5BuyPrice = Math.max(0.01, sma5 - 0.01);                   // 리버스 매수용 (-0.01 차감)
  
      // 1. 매수 주문 로직 (리버스 1일차 매수 금지 포함)
      if (mode === "REVERSE" && previousMode === "NORMAL") {
        buyOrder = "🚫 매수 금지 (리버스 진입 1일차)";
      } else {
        if (newShares <= 0) {
          amt = (principal / n);
          baseQty = Math.floor(amt / largeNum);
          buyOrder = `[LOC] $${largeNum.toFixed(2)} / ${baseQty}주 (최초)`;
        } else if (mode === "REVERSE") {
          baseQty = Math.floor(amt / sma5BuyPrice);
          buyOrder = `[LOC] $${sma5BuyPrice.toFixed(2)} 이하 / ${baseQty}주`;
        } else {
          if (T < n / 2) { // 전반전
            let price1 = Math.min(targetPBuyPrice, largeNum); // 매수용 목표가 적용
            let price2 = Math.min(newAvgPrice, largeNum);     // 평단은 원본 사용
            
            let q1 = Math.floor((amt * 0.5) / price1);
            let totalQty = Math.floor(amt / price2); // ★ 1회 매수금 전체를 price2로 샀을 때의 총 수량
            let q2 = Math.max(0, totalQty - q1);     // ★ 총 수량에서 q1을 뺀 나머지 (혹시 모를 마이너스 방지용 Math.max 적용)
            
            baseQty = q1 + q2;
            
            if (price1 === largeNum && price2 === largeNum) {
              buyOrder = `[LOC] $${largeNum.toFixed(2)} / ${baseQty}주 (전량 🔶큰수)`;
            } else {
              let str1 = (targetPBuyPrice > largeNum) ? `평단🔼: $${price1.toFixed(2)} (🔶큰수)` : `평단🔼: $${price1.toFixed(2)} (⭐%)`;
              let str2 = `평단🔽: $${price2.toFixed(2)}`;
              buyOrder = `[LOC] ${str1} / ${q1}주 \n [LOC] ${str2} / ${q2}주`;
            }
  
        } else { 
            // 후반전: 목표가(평단+P%)와 큰수 중 더 '낮은' 가격을 선택
            let finalPrice = Math.min(targetPBuyPrice, largeNum); // 매수용 목표가 적용
            
            baseQty = Math.floor(amt / finalPrice);
            
            // ★ 어떤 가격이 선택되었는지에 따라 메시지 분리
            if (finalPrice === targetPBuyPrice) {
              buyOrder = `[LOC] $${finalPrice.toFixed(2)} / ${baseQty}주 (⭐%)`;
            } else {
              buyOrder = `[LOC] $${finalPrice.toFixed(2)} / ${baseQty}주 (🔶큰수)`;
            }
          }
        }
        
        // ★ 대폭락 매수 티어
        let crashTiers = "";
        let tierFound = 0;
        let checkQty = baseQty + 1; 
        for (let i = 0; i < 15; i++) { 
          let tierPrice = amt / checkQty;
         if (tierPrice > 0 && tierPrice < largeNum) {
            crashTiers += `\n[추가] $${tierPrice.toFixed(2)} 이하 / +1주`;
            tierFound++;
          }
          if (tierFound >= 5) break; 
          checkQty++; 
        }
        if (crashTiers !== "") buyOrder += crashTiers;
      }
  
      // 2. 매도 주문 로직 (원본 가격 사용 및 리버스 1일/2일차 분리)
      let qQty = Math.floor(newShares * 0.25);
      let revSellQty = Math.floor(newShares / (n / 2));
      
      if (mode === "REVERSE") {
        if (previousMode === "NORMAL") {
          sellOrder1 = `[MOC] ${revSellQty}주 매도`; // 리버스 1일차
        } else {
          sellOrder1 = `[LOC] $${sma5.toFixed(2)} / ${revSellQty}주 매도`; // 리버스 2일차+
        }
        sellOrder2 = "-";
      } else {
        sellOrder1 = `[LOC] $${targetPPrice.toFixed(2)} / ${qQty}주`;
        sellOrder2 = `[지정가] $${(newAvgPrice*(1+targetYield/100)).toFixed(2)} / ${newShares-qQty}주`;
      }
    }
  
  // 대시보드 출력 (% 서식 강제 고정)
    sheet.getRange("D2").setValue(mode);
    sheet.getRange("D3").setValue(T.toFixed(5));
    sheet.getRange("D4").setValue(P / 100).setNumberFormat("0.00%");
    sheet.getRange("D5").setValue(balance.toFixed(2));
    sheet.getRange("D6").setValue(targetYield / 100).setNumberFormat("0.00%");
    sheet.getRange("D7").setValue("$" + largeNum.toFixed(2));
    
    updateVisuals(sheet, sheetName);
    
    const today = Utilities.formatDate(new Date(), Session.getScriptTimeZone(), "yyyy-MM-dd HH:mm:ss");
    
    // ★ DB 기록
    dbSheet.appendRow([
      today, sheetName, mode, closePrice.toFixed(2), newAvgPrice.toFixed(2), newShares, 
      T.toFixed(5), P / 100, sma5.toFixed(2), (newShares*newAvgPrice).toFixed(2), 
      balance.toFixed(2), amt.toFixed(2), todayProfit.toFixed(2), buyOrder, sellOrder1, sellOrder2
    ]);
  
    dbSheet.getRange("H2:H").setNumberFormat("0.00%");
  
    // ★ 사이클 종료 메시지
    if (isCycleEnd) {
      const profitAmt = balance - principal; 
      const profitPct = (profitAmt / principal) * 100; 
  
      const logSheet = getOrCreateLogSheet();
      logSheet.appendRow([new Date(), sheetName, principal, balance, profitAmt.toFixed(2), profitPct.toFixed(2) + "%", finalT.toFixed(5)]);
      
  const endMsg = `🎉 사이클 종료!\n` +
                     `1. 시작 원금: $${principal.toFixed(2)}\n` +
                     `2. 종료 금액: $${balance.toFixed(2)}\n` +
                     `3. 수익금 $${profitAmt.toFixed(2)}, 수익률 ${profitPct >= 0 ? '+' : ''}${profitPct.toFixed(2)}% 달성\n` +
                     `4. 최종 T: ${finalT.toFixed(5)}\n` +
                     `축하합니다!😎`;
      
      sheet.getRange("F2").setValue(endMsg);
    } else {
      sheet.getRange("F2").setValue("✅ 계산 및 기록 완료");
    }
    sheet.getRange("F3").setValue(buyOrder);
    sheet.getRange("F4").setValue(sellOrder1);
    sheet.getRange("F5").setValue(sellOrder2);
  }
  
  // ==========================================
  // 3. UI 시각화
  // ==========================================
  function updateVisuals(sheet, sheetName) {
    sheet.getRange("E6").setValue("누적 실현손익");
    sheet.getRange("F6").setFormula('=IFERROR(SUMIF(DB!$B:$B, "' + sheetName + '", DB!$M:$M), 0)').setNumberFormat("#,##0.00");
    sheet.getRange("J2").setFormula("=IFERROR(B6*B7, 0)").setNumberFormat("$#,##0.00");
    sheet.getRange("J3").setFormula("=IFERROR(B6*B5, 0)").setNumberFormat("$#,##0.00");
    sheet.getRange("J4").setFormula("=IFERROR((B5-B7)*B6, 0)").setNumberFormat("[>0]\"+\"$#,##0.00;[<0]\"-\"$#,##0.00;\"$0.00\"");
    sheet.getRange("I5").setFormula("=IFERROR((B5-B7)/B7, 0)").setNumberFormat("0.00%");
    sheet.getRange("J5").setFormula('=IFERROR(SPARKLINE(I5,{"charttype", "column";"color","FF0000"; "negcolor", "0000FF"; "ymin", -0.2 ; "ymax", +0.2 ;"axis",true ; "axiscolor","000000"}),"")');
    sheet.getRange("J7").setFormula("=IFERROR(D3 / B3, 0)").setNumberFormat("0.00%");
    sheet.getRange("I8").setFormula('=SPARKLINE(J7, {"charttype", "bar"; "max", 1; "color1", IF(J7<0.5, "#4caf50", IF(J7<0.75, "#ff9800", "#f44336"))})');
  }
  
  // ==========================================
  // 4. DB 초기화
  // ==========================================
  function resetDatabase() {
    const sheet = SpreadsheetApp.getActiveSheet();
    const sheetName = sheet.getName();
    
    const ss = SpreadsheetApp.getActiveSpreadsheet();
    const dbSheet = ss.getSheetByName("DB");
    if (!dbSheet) return;
    
    const data = dbSheet.getDataRange().getValues();
    for (let i = data.length - 1; i >= 1; i--) {
      if (data[i][1] === sheetName) dbSheet.deleteRow(i + 1);
    }
    
    sheet.getRange("F2").setValue(`⚠️ [${sheetName}] DB 초기화 완료!`);
  }
  
  // ==========================================
  // 5. 체크박스 감지 트리거 (모바일 대응 UX 강화판)
  // ==========================================
  function onEdit(e) {
    if (!e || !e.range) return;
    const sheet = e.range.getSheet();
    
    if (sheet.getName() === "DB" || sheet.getName() === "수익 일지") return;
  
    const row = e.range.getRow();
    const col = e.range.getColumn();
    const value = e.range.getValue();
  
    if (col === 7 && value === true) {
      if (row === 2) {
        e.range.setValue(false); 
        sheet.getRange("F2").setValue("⏳ 사이클 초기화 중...");
        SpreadsheetApp.flush(); 
        startCycle();
      } else if (row === 3) {
        e.range.setValue(false);
        sheet.getRange("F2").setValue("⏳ 매수표 계산 중...");
        SpreadsheetApp.flush();
        updateDaily();
      } else if (row === 4) {
        e.range.setValue(false);
        sheet.getRange("F2").setValue("🚮 DB 삭제 중...");
        SpreadsheetApp.flush();
        resetDatabase();
      } else if (row === 5) {
        e.range.setValue(false); // 체크박스 체크 해제
        sheet.getRange("F2").setValue("⏳ 수식 복구 중...");
        SpreadsheetApp.flush();
        sheet.getRange("B5").setFormula('=GOOGLEFINANCE(B2,"price")');
        sheet.getRange("D8").setFormula(`=AVERAGE(QUERY(GOOGLEFINANCE(B2, "price", TODAY()-15, TODAY()), "select Col2 order by Col1 desc limit 5 label Col2 ''", 1))`);
        sheet.getRange("F2").setValue("✅ B5, D8 수식 복구 완료!");
      }
    }
  }