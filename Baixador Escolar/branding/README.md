# Branding do EduDownloader

`edudownloader-logo-original.png` é a imagem original aprovada para a interface 1.7. O aplicativo usa esse PNG sem modificar os pixels do arquivo e recorta em memória a área `(300, 185, 950, 835)` para exibir o símbolo na sidebar e na janela.

`edudownloader-symbol.ico` é uma derivação desse mesmo recorte para o ícone do executável Windows. Contém resoluções 16, 24, 32, 48, 64, 128 e 256 px; não é uma nova authority da marca. O `.ico` é consumido somente no build pelo PyInstaller. O PNG original é distribuído em `_internal/branding/` para os ícones da interface em execução.
