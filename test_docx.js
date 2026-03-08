const htmlToDocx = require('html-to-docx');
const html = `<!DOCTYPE html><html lang="pt-BR"><head><meta charset="UTF-8"><title>Parecer</title></head><body><p>Teste</p></body></html>`;
(async () => {
    try {
        console.log("Gerando blob...");
        const buffer = await htmlToDocx(html);
        console.log("Sucesso, bytes:", buffer.length);
    } catch(e) {
        console.error("ERRO COMPILANDO DOCX:", e);
    }
})();
