class IndicatorsMixin:
	def _calc_ma(self, prices, period):
		"""이동평균 계산 - prices는 최신순(인덱스 0이 최신봉)"""
		if len(prices) < period:
			return None
		return sum(prices[:period]) / period

	def _calc_rsi(self, prices, period=14):
		if len(prices) < period + 1:
			return None
		ordered = list(reversed(prices[:period + 1]))
		gains, losses = [], []
		for i in range(1, len(ordered)):
			diff = ordered[i] - ordered[i - 1]
			gains.append(max(diff, 0))
			losses.append(max(-diff, 0))
		avg_gain = sum(gains) / period
		avg_loss = sum(losses) / period
		if avg_loss == 0:
			return 100.0
		rs = avg_gain / avg_loss
		return 100 - (100 / (1 + rs))
