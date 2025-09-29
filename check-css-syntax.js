const fs = require('fs');

// Read the CSS file
const cssContent = fs.readFileSync('publication-organizer/public/style.css', 'utf8');

// Simple brace matching
let openBraces = 0;
let closeBraces = 0;
let lineNum = 1;

for (let i = 0; i < cssContent.length; i++) {
    if (cssContent[i] === '\n') {
        lineNum++;
    }
    if (cssContent[i] === '{') {
        openBraces++;
    } else if (cssContent[i] === '}') {
        closeBraces++;
    }
}

console.log(`Open braces: ${openBraces}`);
console.log(`Close braces: ${closeBraces}`);

if (openBraces !== closeBraces) {
    console.log(`MISMATCH: ${Math.abs(openBraces - closeBraces)} ${openBraces > closeBraces ? 'unclosed' : 'extra'} braces`);
} else {
    console.log('All braces are properly matched!');
}