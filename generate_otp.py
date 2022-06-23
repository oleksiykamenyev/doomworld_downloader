import pyotp

with open('otp.txt', encoding='utf-8') as otp_stream:
    otp = otp_stream.read().strip()

totp = pyotp.TOTP(otp)
print(totp.now())
