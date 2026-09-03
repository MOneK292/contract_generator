"""CLI script to obtain Google OAuth2 refresh_token for Google Sheets and Google Drive."""

import argparse
import json
import os
import sys
import urllib.parse
import urllib.request

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
    "https://www.googleapis.com/auth/drive.readonly",
]


def generate_auth_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",
        "prompt": "consent",
    }
    return f"https://accounts.google.com/o/oauth2/v2/auth?{urllib.parse.urlencode(params)}"


def exchange_code_for_tokens(code: str, client_id: str, client_secret: str, redirect_uri: str) -> dict:
    data = urllib.parse.urlencode({
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
        "grant_type": "authorization_code",
    }).encode("utf-8")

    req = urllib.request.Request(
        "https://oauth2.googleapis.com/token",
        data=data,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main():
    parser = argparse.ArgumentParser(description="Google OAuth2 Token Generator")
    parser.add_argument(
        "--client-id",
        default=os.environ.get("GOOGLE_OAUTH_CLIENT_ID", ""),
        help="Google OAuth2 Client ID (or set GOOGLE_OAUTH_CLIENT_ID)",
    )
    parser.add_argument(
        "--client-secret",
        default=os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET", ""),
        help="Google OAuth2 Client Secret (or set GOOGLE_OAUTH_CLIENT_SECRET)",
    )
    parser.add_argument(
        "--redirect-uri",
        default="http://localhost:8080",
        help="Redirect URI configured in Google Cloud Console (default: http://localhost:8080)",
    )
    args = parser.parse_args()

    client_id = args.client_id.strip()
    client_secret = args.client_secret.strip()
    redirect_uri = args.redirect_uri.strip()

    if not client_id or not client_secret:
        print("Error: --client-id and --client-secret must be provided via CLI flags or env vars.", file=sys.stderr)
        print("Usage: python get_oauth_tokens.py --client-id YOUR_ID --client-secret YOUR_SECRET", file=sys.stderr)
        sys.exit(1)

    print("=" * 60)
    print("Google OAuth2 Token Generator")
    print("=" * 60)
    print(f"Client ID: {client_id}")
    print(f"Redirect URI: {redirect_uri}\n")
    
    auth_url = generate_auth_url(client_id, redirect_uri)
    print("1. Откройте эту ссылку в браузере под вашим Google-аккаунтом:")
    print(f"\n{auth_url}\n")
    print("2. После входа и подтверждения разрешений браузер перенаправит вас на страницу с ошибкой (или пустую).")
    print("3. Скопируйте из адресной строки браузера всю ссылку (или значение параметра ?code=...) и вставьте сюда:\n")
    
    auth_response = input("Вставьте скопированный URL или код: ").strip()
    if not auth_response:
        print("Ошибка: код не введен.")
        return

    # Extract code if full URL was pasted
    if "code=" in auth_response:
        parsed = urllib.parse.urlparse(auth_response)
        params = urllib.parse.parse_qs(parsed.query)
        code = params.get("code", [None])[0]
        if not code and parsed.fragment:
            params = urllib.parse.parse_qs(parsed.fragment)
            code = params.get("code", [None])[0]
    else:
        code = auth_response

    if not code:
        print("Не удалось извлечь параметр code.")
        return

    # Decode urlencoded code if needed
    code = urllib.parse.unquote(code)

    print("\nОбмен кода на refresh_token...")
    try:
        tokens = exchange_code_for_tokens(code, client_id, client_secret, redirect_uri)
        refresh_token = tokens.get("refresh_token")
        if not refresh_token:
            print("Предупреждение: Google не вернул refresh_token. Возможно, уже был выдан ранее.")
            print(f"Ответ Google: {tokens}")
            return
        
        print("\n" + "=" * 60)
        print("УСПЕХ! Получен REFRESH_TOKEN:")
        print(refresh_token)
        print("=" * 60)
    except Exception as e:
        print(f"\nОшибка при получении токена: {e}")


if __name__ == "__main__":
    main()
