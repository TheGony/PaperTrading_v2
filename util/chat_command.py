from strategy.indicators import IndicatorsMixin
from strategy.selector import StockSelectorMixin
from strategy.orb_selector import OrbSelectorMixin
from engine.reporter import ReporterMixin
from engine.entry import EntryMixin
from engine.exit import ExitMixin
from engine.trader import TraderMixin
from bot.commands import BotCommandsMixin


class ChatCommand(
	IndicatorsMixin,
	StockSelectorMixin,
	OrbSelectorMixin,
	EntryMixin,
	ExitMixin,
	ReporterMixin,
	TraderMixin,
	BotCommandsMixin,
):
	def __init__(self):
		self.token                  = None   # 현재 사용 중인 토큰
		self.is_running             = False  # 프로세스 실행 여부
		self.trading_task           = None   # 트레이딩 백그라운드 태스크
		self.profit_check_task      = None   # 수익율 체크 백그라운드 태스크
		self.selected_stocks        = []     # 선정된 종목 코드 리스트
		self.selected_stocks_names  = {}     # 종목코드 → 종목명 매핑
		self.selected_stocks_meta   = {}     # 종목코드 → {flu_rt, score, is_foreign}
		self.last_chart_check_time  = None   # 마지막 차트 체크 시간
		self.sell_cooldown          = {}     # 매도 후 재매수 금지 추적 {stk_cd: 매도시각}
		self.daily_loss_count       = {}     # 당일 종목별 손실 횟수 {stk_cd: count}
		self.entry_time             = {}     # 매수 체결 시각 {stk_cd: datetime}
		self.entry_snapshot         = {}     # 매수 시점 스냅샷 {stk_cd: dict}
		self.peak_profit            = {}     # 트레일링 스탑용 종목별 최고 수익률 {stk_cd: max_pl_rt}
		self.min_profit             = {}     # MAE 추적: 보유 중 최저 수익률 {stk_cd: min_pl_rt}
		self.trade_log              = []     # 당일 매매 기록
		self.current_phase          = None   # 현재 장 구간 (phase transition 감지용)
		self.early_buy_count        = 0      # 장초반 매수 횟수 (최대 5회)
		self.orb_data               = {}     # ORB 고점/저점 캐시 {stk_cd: {'high', 'low', 'gap_up'}}
		self.orb_buy_count          = 0      # 장초반 ORB 매수 횟수 (최대 2회)
		self.orb_candidates         = []     # ORB 전용 후보 리스트 (장 시작 1회 선정, 갱신 없음)
