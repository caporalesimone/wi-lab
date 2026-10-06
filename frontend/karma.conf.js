const fs = require('fs');
const path = require('path');

// Writes test-results/summary.json (counts, duration, failed test names) for the CI job summary.
function SummaryReporter() {
  const failures = [];
  let startedAt = Date.now();
  this.onRunStart = () => { startedAt = Date.now(); };
  this.onSpecComplete = (browser, result) => {
    if (result.success === false && !result.skipped) {
      failures.push(result.suite.concat(result.description).join(' '));
    }
  };
  this.onRunComplete = (browsers, results) => {
    const dir = path.join(__dirname, 'test-results');
    fs.mkdirSync(dir, { recursive: true });
    fs.writeFileSync(path.join(dir, 'summary.json'), JSON.stringify({
      success: results.success,
      failed: results.failed,
      skipped: results.skipped || 0,
      durationMs: Date.now() - startedAt,
      failures
    }));
  };
}

module.exports = function (config) {
  config.set({
    basePath: '',
    frameworks: ['jasmine', '@angular-devkit/build-angular'],
    plugins: [
      require('karma-jasmine'),
      require('karma-chrome-launcher'),
      require('karma-jasmine-html-reporter'),
      require('karma-coverage'),
      require('@angular-devkit/build-angular/plugins/karma'),
      { 'reporter:wilab-summary': ['type', SummaryReporter] }
    ],
    reporters: ['progress', 'kjhtml', 'wilab-summary'],
    // Used when running with --code-coverage (the CI does)
    coverageReporter: {
      dir: path.join(__dirname, 'coverage'),
      subdir: '.',
      reporters: [{ type: 'text-summary' }, { type: 'json-summary' }]
    },
    browsers: ['Chrome'],
    customLaunchers: {
      ChromeHeadlessCI: { base: 'ChromeHeadless', flags: ['--no-sandbox'] }
    },
    restartOnFileChange: true
  });
};
