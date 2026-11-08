/*
 * Phonon runtime (development / folder build).
 *
 * Loads the `phonon-tts` browser package and the Phonon 31M checkpoint from
 * the local `vendor/` directory. `build.py` replaces this whole file with an
 * embedded version that carries the same package + model inside the HTML.
 */
(function () {
  'use strict';

  var PKG_BASE = './vendor/phonon-tts/';
  var MODEL_BASE = './vendor/phonon-model/';

  var instance = null;
  var loading = null;

  function modelSpec() {
    return {
      weights: { q8: MODEL_BASE + 'model.q8.gguf' },
      tokenizer: MODEL_BASE + 'tokenizer.json',
      config: MODEL_BASE + 'config.json',
      voices: { default: MODEL_BASE + 'default-voice.safetensors' },
      defaultVoice: 'default'
    };
  }

  async function getTTS(onProgress) {
    if (instance) return instance;
    if (loading) return loading;

    loading = (async function () {
      var mod = await import(PKG_BASE + 'index.js');
      instance = await mod.PhononTTS.load({
        lang: 'en',
        model: modelSpec(),
        quant: 'q8',
        device: 'auto',
        threads: 1,
        cache: true,
        onProgress: onProgress
      });
      return instance;
    })();

    return loading;
  }

  window.PhononRuntime = {
    getTTS: getTTS,
    get instance() { return instance; },
    get loading() { return loading; },
    isReady: function () { return !!instance; },
    modelSpec: modelSpec
  };
})();
