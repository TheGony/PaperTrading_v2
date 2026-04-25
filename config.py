# 실제투자로 진행할 시 True를 False로 변경
is_paper_trading = True

# 따옴표 안에 작성할 것
real_app_key = "0Bl-mLhz8B3Mz2oIfQIb5n1t-_C6tmFtijrJ9gO4FxM"
real_app_secret = "FmZ38_ytl8KH1s5zyf1EIlm8IImHb8c9H_XtQYq49QM"

paper_app_key = "FQbObMtYr4xxI_XLgVJaOLxi5a-CsQE44WfYiLr3ARY"
paper_app_secret = "OL_T9iizFRnWB4Ems3JFHTIM6ip5LqtLwlZ-KNUwzMQ"

real_host_url = "https://api.kiwoom.com"
paper_host_url = "https://mockapi.kiwoom.com"

real_socket_url = "wss://api.kiwoom.com:10000"
paper_socket_url = "wss://mockapi.kiwoom.com:10000"

app_key = paper_app_key if is_paper_trading else real_app_key
app_secret = paper_app_secret if is_paper_trading else real_app_secret
host_url = paper_host_url if is_paper_trading else real_host_url
socket_url = paper_socket_url if is_paper_trading else real_socket_url

telegram_chat_id = "8238805706"
telegram_token = "8798831319:AAEnHU68hRhl58f7z2V9T1OJPb81BLiTJKw"