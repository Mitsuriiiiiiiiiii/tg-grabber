from telethon.sessions import StringSession

s = "1BJWap1sBuwW9tuzScr3d5BgsX01G2TK-SQmkIb6fhhqYorCAcCe_cERNPQcMVih1HaK024sqYB3MNgsaECZ8Af8j6bHI1jdIXBP8hp1vcsGEiEC1cs9w6zYtL_bPi_uOoRJKIQW4I43DxG9G25tt5w2nRDnQl-lbbcVIjguOOzo2wjRNBWlimubv-_ZHUvgDWWYOeX5ZrTwL2mA4FuybnVJdLOO-PW9DtP0Pob5fjMEWkJYZn9ezHX1BabEd7QXoxyeXHiQjU0zAz_b6jC40KEBxTgBWmOaXf8AsYeEMwAF_B3pHi6IamdEsyAddBl3He_7n3OnKpOWIH4CUuI5NDwClAuwrVuM="

try:
    session = StringSession(s)
    print("Décodage réussi")
    print("DC ID :", session.dc_id)
    print("Clé d'autorisation présente :", bool(session.auth_key))
except Exception as e:
    print("Erreur :", type(e).__name__, str(e))
