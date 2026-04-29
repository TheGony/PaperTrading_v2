import asyncio
from api.chart import fn_ka10080_full
from api.ranking import fn_ka10032, fn_ka10023
from util.tel_send import tel_send
from util.logger import get_logger


class OrbSelectorMixin:
	ORB_CANDIDATES_MAX = 15
	ORB_MIN_CANDIDATES = 5

	async def _get_orb_candidates(self, is_refresh=False):
		"""ORB 전용 후보 선정. 결과를 self.orb_candidates에 저장."""
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

			# 하드 필터: 갭 하락(갭 ≤ 0) 종목만 제외
			if gap <= 0:
				continue

			# 하드 필터: -2% 눌림까지 허용 (기존 현재가 ≥ 시가 → 완화)
			cur_prc = candles[0]['cur_prc']
			if cur_prc < day_open * 0.98:
				continue

			latest_high      = candles[0]['high_pric']
			upper_tail_ratio = (latest_high - cur_prc) / latest_high if latest_high > 0 else 0
			bearish_count    = sum(1 for c in open_candles if c['cur_prc'] < c['open_pric'])

			# 소프트 패널티 (조건 이탈 시 감점, 탈락은 없음)
			penalty = 0.0
			if not (1.5 <= gap <= 8.0):  # 이상적 갭 범위 이탈
				penalty += 0.2
			if upper_tail_ratio > 0.05:  # 윗꼬리 > 5%
				penalty += 0.2
			if bearish_count >= 2:       # 음봉 2개 이상
				penalty += 0.2

			candidates.append({
				'stk_cd':     stk_cd,
				'stk_nm':     s.get('stk_nm', stk_cd),
				'gap':        round(gap, 2),
				'flu_rt':     s.get('flu_rt', 0),
				'trde_prica': s.get('trde_prica', 0),
				'sdnin_rt':   sdnin_map.get(stk_cd),
				'penalty':    penalty,
			})

		# 스코어링: sdnin_rt 없으면 패널티(0.3)로 살림
		if candidates:
			max_sdnin = max((c['sdnin_rt'] for c in candidates if c['sdnin_rt'] is not None), default=1) or 1
			max_flu   = max(c['flu_rt']     for c in candidates) or 1
			max_trde  = max(c['trde_prica'] for c in candidates) or 1
			for c in candidates:
				sdnin_rt    = c['sdnin_rt']
				volume_norm = (sdnin_rt / max_sdnin) if sdnin_rt is not None else 0.3
				c['score']  = (
					volume_norm                  * 0.40 +
					(c['flu_rt']     / max_flu)  * 0.35 +
					(c['trde_prica'] / max_trde) * 0.25
					- c['penalty']
				)
			candidates.sort(key=lambda x: x['score'], reverse=True)

		# 최소 후보 보장: 5개 미만이면 거래대금 상위로 보충 (캔들 필터 생략)
		if len(candidates) < self.ORB_MIN_CANDIDATES:
			existing = {c['stk_cd'] for c in candidates}
			added    = 0
			for s in raw:
				if len(candidates) >= self.ORB_MIN_CANDIDATES:
					break
				if s['stk_cd'] in existing:
					continue
				candidates.append({
					'stk_cd':     s['stk_cd'],
					'stk_nm':     s.get('stk_nm', s['stk_cd']),
					'gap':        None,  # 캔들 미조회
					'flu_rt':     s.get('flu_rt', 0),
					'trde_prica': s.get('trde_prica', 0),
					'sdnin_rt':   sdnin_map.get(s['stk_cd']),
					'score':      -0.5,
					'penalty':    0.0,
				})
				existing.add(s['stk_cd'])
				added += 1
			if added > 0:
				tel_send(f"⚠️ [ORB] 후보 부족 → 거래대금 상위 {added}종목 보충 (총 {len(candidates)}종목)")

		if not candidates:
			label = "2차 갱신" if is_refresh else "선정"
			tel_send(f"⚠️ [ORB] 조건을 충족하는 후보 없음 ({label})")
			self.orb_candidates = []
			return []

		candidates.sort(key=lambda x: x['score'], reverse=True)
		self.orb_candidates = candidates[:self.ORB_CANDIDATES_MAX]

		names = ', '.join(
			f"{c['stk_nm']}({c['stk_cd']}) gap={c['gap']:+.1f}%" if c['gap'] is not None
			else f"{c['stk_nm']}({c['stk_cd']}) gap=N/A"
			for c in self.orb_candidates
		)
		label = "2차 갱신" if is_refresh else "선정"
		tel_send(f"✅ [ORB] 후보 {len(self.orb_candidates)}종목 {label}\n   {names}")
		log.info(f'[ORB 선정] {names}')
		return self.orb_candidates
