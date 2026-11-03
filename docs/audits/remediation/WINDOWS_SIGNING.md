# Windows release signing

`tools/packaging/sign_release.ps1` is the opt-in release path for Authenticode
signing. It uses a code-signing certificate already installed in the current
user's `Cert:\CurrentUser\My` store. It never creates or substitutes a
certificate. The app and installer are only signed when a valid thumbprint,
timestamp URL, Windows SDK `signtool.exe`, and Inno Setup compiler are present.

## Release sequence

1. Build the desktop executable using the regular `nedotify-build` steps:
   PyInstaller first, then use the signing script for the release installer.
   The script expects `dist\NeDotify.exe` to exist.
2. Find the intended certificate thumbprint in the Windows certificate store
   and confirm its private key is available to the current user. A certificate
   must be valid now and include the Code Signing EKU.
3. Validate prerequisites without changing files or contacting a timestamp
   service:

   ```powershell
   .\tools\packaging\sign_release.ps1 -Thumbprint "<40-character-thumbprint>" `
     -TimestampServer "https://<approved-rfc3161-timestamp-service>" -ValidateOnly
   ```

4. Sign the executable, compile the installer with release signing enabled,
   then verify both outputs:

   ```powershell
   .\tools\packaging\sign_release.ps1 -Thumbprint "<40-character-thumbprint>" `
     -TimestampServer "https://<approved-rfc3161-timestamp-service>"
   ```

   The script signs `dist\NeDotify.exe`, invokes ISCC with an explicit
   `NeDotifyRelease` SignTool configured for SHA-256 plus RFC 3161 timestamping,
   and checks `dist\NeDotify_Setup.exe` with `Get-AuthenticodeSignature`. The
   `NEDOTIFY_RELEASE_SIGNING` define enables `SignTool` and
   `SignedUninstaller=yes` in `installer.iss`. A normal local Inno compile does
   not set that define and remains unsigned.

5. In an isolated Windows release-validation VM/account, install the candidate
   without launching NeDotify and verify the generated `unins*.exe`:

   ```powershell
   .\tools\packaging\sign_release.ps1 -Thumbprint "<40-character-thumbprint>" `
     -VerifyUninstallerPath "$env:LOCALAPPDATA\Programs\NeDotify\unins000.exe"
   ```

   Inno signs its uninstaller template through the same SignTool command during
   compilation; the installed executable is the final Authenticode artifact
   to inspect. The verification mode checks both `Status=Valid` and the
   expected signer thumbprint.

## Failure behavior and limits

The script stops before signing if the thumbprint is absent or malformed, the
certificate is missing, expired, has no accessible private key, or lacks the
Code Signing EKU. It also stops if `signtool.exe`, ISCC, the built executable,
or a timestamp URL is missing. Each signed output is checked for a valid
Authenticode result and the requested signer.

The repository has no trusted signing certificate today. Therefore no actual
artifact is signed by this change, and the release process must supply the
organization's trusted certificate and approved timestamp service. A green
source test does not establish publisher trust; that still depends on the
certificate chain and Windows policy on the target machine.

Inno Setup behavior referenced here: [SignTool](https://jrsoftware.org/ishelp/topic_setup_signtool.htm),
[SignedUninstaller](https://jrsoftware.org/ishelp/topic_setup_signeduninstaller.htm),
and [ISCC command-line options](https://jrsoftware.org/ishelp/topic_compilercmdline.htm).
