import requests
import json
from util.config import host_url
from util.logger import get_logger

# 주식 매수주문 (kt10000) - 시장가
def fn_kt10000(stk_cd, ord_qty, ord_uv, cont_yn='N', next_key='', token=None):
	# 1. 요청할 API URL
	endpoint = '/api/dostk/ordr'
	url = host_url + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'kt10000', # TR명
	}

	# 3. 요청 데이터
	params = {
		'dmst_stex_tp': 'KRX', # 국내거래소구분 KRX,NXT,SOR
		'stk_cd': stk_cd, # 종목코드
		'ord_qty': f'{ord_qty}', # 주문수량
		'ord_uv': '', # 주문단가 (시장가 주문이므로 빈값)
		'trde_tp': '3', # 매매구분 0:보통 , 3:시장가 , 5:조건부지정가 , 81:장마감후시간외 , 61:장시작전시간외, 62:시간외단일가 , 6:최유리지정가 , 7:최우선지정가 , 10:보통(IOC) , 13:시장가(IOC) , 16:최유리(IOC) , 20:보통(FOK) , 23:시장가(FOK) , 26:최유리(FOK) , 28:스톱지정가,29:중간가,30:중간가(IOC),31:중간가(FOK)
		'cond_uv': '', # 조건단가
	}

	# 4. http POST 요청 (타임아웃 + 예외처리)
	try:
		response = requests.post(url, headers=headers, json=params, timeout=10)
		response.raise_for_status()
		data = response.json()

		# 5. 응답 상태 코드와 데이터 출력
		print('Code:', response.status_code)
		print('Header:', json.dumps({key: response.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
		print('Body:', json.dumps(data, indent=4, ensure_ascii=False))  # JSON 응답을 파싱하여 출력

		return data.get('return_code', -1)
	except Exception as e:
		get_logger().error(f'[kt10000] {stk_cd} 매수 요청 실패: {e}')
		return -1


# 주식 매도주문 (kt10001) - 시장가
def fn_kt10001(stk_cd, ord_qty, cont_yn='N', next_key='', token=None):
	log = get_logger()

	# 1. 요청할 API URL
	endpoint = '/api/dostk/ordr'
	url = host_url + endpoint

	# 2. header 데이터
	headers = {
		'Content-Type': 'application/json;charset=UTF-8', # 컨텐츠타입
		'authorization': f'Bearer {token}', # 접근토큰
		'cont-yn': cont_yn, # 연속조회여부
		'next-key': next_key, # 연속조회키
		'api-id': 'kt10001', # TR명
	}

	# 3. 요청 데이터
	params = {
		'dmst_stex_tp': 'KRX', # 국내거래소구분 KRX,NXT,SOR
		'stk_cd': stk_cd, # 종목코드
		'ord_qty': ord_qty, # 주문수량
		'ord_uv': '', # 주문단가
		'trde_tp': '3', # 매매구분 0:보통 , 3:시장가 , 5:조건부지정가 , 81:장마감후시간외 , 61:장시작전시간외, 62:시간외단일가 , 6:최유리지정가 , 7:최우선지정가 , 10:보통(IOC) , 13:시장가(IOC) , 16:최유리(IOC) , 20:보통(FOK) , 23:시장가(FOK) , 26:최유리(FOK) , 28:스톱지정가,29:중간가,30:중간가(IOC),31:중간가(FOK)
		'cond_uv': '', # 조건단가
	}

	# 4. http POST 요청 (타임아웃 + 예외처리)
	try:
		response = requests.post(url, headers=headers, json=params, timeout=10)
		response.raise_for_status()
		data = response.json()

		# 5. 응답 상태 코드와 데이터 출력
		print('Code:', response.status_code)
		print('Header:', json.dumps({key: response.headers.get(key) for key in ['next-key', 'cont-yn', 'api-id']}, indent=4, ensure_ascii=False))
		print('Body:', json.dumps(data, indent=4, ensure_ascii=False))

		return_code = data.get('return_code', -1)
		log.info(f'[kt10001] {stk_cd} {ord_qty}주 매도 요청 → return_code={return_code}')
		return return_code
	except Exception as e:
		log.error(f'[kt10001] {stk_cd} 매도 요청 실패: {e}')
		return -1
