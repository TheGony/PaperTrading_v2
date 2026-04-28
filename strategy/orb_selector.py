import asyncio
from api.chart import fn_ka10080_full
from api.ranking import fn_ka10032, fn_ka10023
from util.tel_send import tel_send
from util.logger import get_logger


class OrbSelectorMixin:
	ORB_CANDIDATES_MAX = 15

	async def _get_orb_candidates(self):
		"""ORB 전용 후보 선정. 장 시작 직후 1회만 호출. 결과를 self.orb_candidates에 저장."""
		log = get_logger()

		# 거래대금 상위 50개 (메인) + 거래량급증 50개 (보조 — sdnin_rt 확보)
		raw_trde, raw_vol = await asyncio.gather(
			asyncio.get_event_loop().run_in_executor(None, fn_ka10032, 50, 'N', '', self.token),
			asyncio.get_event_loop().run_in_executor(None, fn_ka10023, 50, 'N', '', self.token),
		)
		if not raw_trde:
			tel_send("⚠️ [ORB] 후보 조회 실패 (거래대금 API 응답 없음)")
			self.orb_candidates = []
			return []

		# 거래량급증 API에 없는 종목은 None → 캔들 필터 이후 제외
		sdnin_map = {s['stk_cd']: s.get('sdnin_rt') for s in (raw_vol or [])}

		raw = [s for s in raw_trde if not self._is_excluded(s.get('stk_nm', ''))]

		def _hhmm(t):
			t = str(t).strip()
			return t[8:12] if len(t) >= 14 else t[0:4]

		candidates = []
		for s in raw:
			stk_cd  = s['stk_cd']
			candles = await asyncio.get_event_loop().run_in_executor(
				None, fn_ka10080_full, stk_cd, 15, 'N', '', self.token
			)
			await asyncio.sleep(0.2)
			if not candles:
				continue

			# 09:00~09:04 봉 추출
			open_candles = [c for c in candles if '0900' <= _hhmm(c['cntr_tm']) <= '0904']
			if not open_candles:
				continue

			# 갭 계산: (당일 시가 - 전일 종가) / 전일 종가 * 100
			first      = open_candles[-1]  # 09:00봉 (가장 오래된)
			day_open   = first['open_pric']
			prev_close = first['cur_prc'] - first['pred_pre']
			if prev_close <= 0 or day_open <= 0:
				continue
			gap = (day_open - prev_close) / prev_close * 100

			# 갭 필터: +2% ~ +7%
			if not (2.0 <= gap <= 7.0):
				continue

			# 현재가 >= 시가 (밀리는 종목 제거)
			cur_prc = candles[0]['cur_prc']
			if cur_prc < day_open:
				continue

			# 윗꼬리 필터: (고가 - 현재가) / 고가 <= 5%
			latest_high = candles[0]['high_pric']
			if latest_high > 0 and (latest_high - cur_prc) / latest_high > 0.05:
				continue

			# 음봉 1개까지 허용 (0~1개 음봉)
			bearish_count = sum(1 for c in open_candles if c['cur_prc'] < c['open_pric'])
			if bearish_count > 1:
				continue

			sdnin_rt = sdnin_map.get(stk_cd)
			if sdnin_rt is None:
				continue  # 거래량급증 데이터 없음 → ORB 후보 제외

			candidates.append({
				'stk_cd':    stk_cd,
				'stk_nm':    s.get('stk_nm', stk_cd),
				'gap':       round(gap, 2),
				'flu_rt':    s.get('flu_rt', 0),
				'trde_prica': s.get('trde_prica', 0),
				'sdnin_rt':  sdnin_rt,
			})

		if not candidates:
			tel_send("⚠️ [ORB] 조건을 충족하는 후보 없음 (갭/캔들 필터)")
			self.orb_candidates = []
			return []

		# 스코어: 거래량증가 40% + 등락률 35% + 거래대금 25%
		max_sdnin = max(c['sdnin_rt']   for c in candidates) or 1
		max_flu   = max(c['flu_rt']     for c in candidates) or 1
		max_trde  = max(c['trde_prica'] for c in candidates) or 1
		for c in candidates:
			c['score'] = (
				(c['sdnin_rt']   / max_sdnin) * 0.4 +
				(c['flu_rt']     / max_flu)   * 0.35 +
				(c['trde_prica'] / max_trde)  * 0.25
			)

		candidates.sort(key=lambda x: x['score'], reverse=True)
		self.orb_candidates = candidates[:self.ORB_CANDIDATES_MAX]

		names = ', '.join(
			f"{c['stk_nm']}({c['stk_cd']}) gap={c['gap']:.1f}%"
			for c in self.orb_candidates
		)
		tel_send(f"✅ [ORB] 후보 {len(self.orb_candidates)}종목 선정\n   {names}")
		log.info(f'[ORB 선정] {names}')
		return self.orb_candidates
