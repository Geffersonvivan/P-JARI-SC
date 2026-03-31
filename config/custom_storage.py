from whitenoise.storage import CompressedManifestStaticFilesStorage

class TolerantWhiteNoiseStorage(CompressedManifestStaticFilesStorage):
    manifest_strict = False
