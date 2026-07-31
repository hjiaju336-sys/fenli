const fs = require('fs');
const js = fs.readFileSync('D:/project/规则怪谈/fenli/mvp/static/_debug_js.js', 'utf8');

// Simple approach: split on function boundaries and test each
// Just find the line where it breaks by binary testing
function isValid(code) {
    try {
        new Function(code);
        return true;
    } catch(e) {
        return false;
    }
}

// Test in chunks
const lines = js.split('\n');
let goodLines = 0;
let lastGood = 0;

for (let chunkSize = 1000; goodLines < lines.length; ) {
    const end = Math.min(goodLines + chunkSize, lines.length);
    const testCode = lines.slice(0, end).join('\n');
    if (isValid(testCode)) {
        goodLines = end;
        lastGood = end;
    } else {
        if (chunkSize === 1) {
            console.log('Error after line ' + lastGood);
            console.log('Line ' + (lastGood + 1) + ': ' + (lines[lastGood] ? lines[lastGood].substring(0, 200) : '(empty)'));
            console.log('Line ' + lastGood + ': ' + (lines[lastGood - 1] ? lines[lastGood - 1].substring(0, 200) : '(empty)'));

            // Show context
            const start = Math.max(0, lastGood - 5);
            for (let i = start; i <= Math.min(lastGood + 5, lines.length - 1); i++) {
                console.log('  [' + (i+1) + '] ' + (lines[i] ? lines[i].substring(0, 150) : '(empty)'));
            }
            process.exit(0);
        }
        chunkSize = Math.max(1, Math.floor(chunkSize / 2));
    }
}
