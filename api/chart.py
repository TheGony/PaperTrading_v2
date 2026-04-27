import requests
import json
import time
from util.config import host_url
from util.logger import get_logger

# 주식분봉차트조회요청 - 1분봉 기준 여러 봉의 종가 리스트 반환 (최신순)
def fn_ka10080(stk_cd, count=30, cont_yn='N', next_key='', token=None):
	log = get_logger()
	url = host_url + '/api/dostk/chart'

	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10080',
	}

	params = {
		'stk_cd': stk_cd,
		'tic_scope': '1',
		'upd_stkpc_tp': '1',
	}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10080] {stk_cd} 429 rate limit, {wait}초 후 재시도 ({attempt+1}/3)')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10080] {stk_cd} 요청 실패: {e}')
				return [], [], [], []
			log.warning(f'[ka10080] {stk_cd} 요청 실패 ({attempt+1}/3): {e}')
			time.sleep((attempt + 1) * 2)
	else:
		return [], [], [], []

	chart_data = data.get('stk_min_pole_chart_qry', [])
	if not chart_data:
		log.warning(f'[ka10080] {stk_cd} 데이터 없음 (status={response.status_code}) body={json.dumps(data, ensure_ascii=False)}')
	else:
		log.debug(f'[ka10080] {stk_cd} {len(chart_data)}봉 수신 (status={response.status_code})')

	# 최신순으로 count개의 종가 + 거래량 + 시가 + 고가 리스트 반환
	prices = []
	volumes = []
	open_prices = []
	highs = []
	for candle in chart_data[:count]:
		def _parse_price(val):
			if isinstance(val, str) and val.startswith('-'):
				val = val[1:]
			try:
				return float(val)
			except (ValueError, TypeError):
				return 0.0

		prices.append(_parse_price(candle.get('cur_prc', '0')))
		open_prices.append(_parse_price(candle.get('open_pric', '0')))
		highs.append(_parse_price(candle.get('high_pric', '0')))

		trde_qty = candle.get('trde_qty', '0')
		try:
			volumes.append(float(str(trde_qty).replace(',', '')))
		except (ValueError, TypeError):
			volumes.append(0.0)

	return prices, volumes, open_prices, highs  # 최신봉 기준 내림차순


def fn_ka10080_full(stk_cd, count=30, cont_yn='N', next_key='', token=None):
	"""1분봉 전체 필드 반환 (ORB용). 최신순 리스트 of dict"""
	log = get_logger()
	url = host_url + '/api/dostk/chart'
	headers = {
		'Content-Type': 'application/json;charset=UTF-8',
		'authorization': f'Bearer {token}',
		'cont-yn': cont_yn,
		'next-key': next_key,
		'api-id': 'ka10080',
	}
	params = {'stk_cd': stk_cd, 'tic_scope': '1', 'upd_stkpc_tp': '1'}

	for attempt in range(3):
		try:
			response = requests.post(url, headers=headers, json=params, timeout=10)
			if response.status_code == 429:
				wait = (attempt + 1) * 2
				log.warning(f'[ka10080_full] {stk_cd} 429, {wait}초 후 재시도')
				time.sleep(wait)
				continue
			response.raise_for_status()
			data = response.json()
			break
		except Exception as e:
			if attempt == 2:
				log.error(f'[ka10080_full] {stk_cd} 요청 실패: {e}')
				return []
			time.sleep((attempt + 1) * 2)
	else:
		return []

	def _p(val):
		s = str(val).strip().replace(',', '')
		neg = s.startswith('-')
		try:
			return -float(s[1:]) if neg else float(s.lstrip('+'))
		except (ValueError, TypeError):
			return 0.0

	result = []
	for candle in data.get('stk_min_pole_chart_qry', [])[:count]:
		try:
			vol = float(str(candle.get('trde_qty', '0')).replace(',', ''))
		except (ValueError, TypeError):
			vol = 0.0
		result.append({
			'cur_prc':   abs(_p(candle.get('cur_prc',   '0'))),
			'open_pric': abs(_p(candle.get('open_pric', '0'))),
			'high_pric': abs(_p(candle.get('high_pric', '0'))),
			'low_pric':  abs(_p(candle.get('low_pric',  '0'))),
			'trde_qty':  vol,
			'cntr_tm':   str(candle.get('cntr_tm', '')).strip(),
			'pred_pre':  _p(candle.get('pred_pre', '0')),
		})
	return result
