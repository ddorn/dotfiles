" Automatic install of vim-plug
let data_dir = has('nvim') ? stdpath('data') . '/site' : '~/.vim'
if empty(glob(data_dir . '/autoload/plug.vim'))
  silent execute '!curl -fLo '.data_dir.'/autoload/plug.vim --create-dirs  https://raw.githubusercontent.com/junegunn/vim-plug/master/plug.vim'
  autocmd VimEnter * PlugInstall --sync | source $MYVIMRC
endif

call plug#begin('~/.vim/plugged')

Plug 'wakatime/vim-wakatime' " Time tracking

Plug 'github/copilot.vim'
Plug 'scrooloose/nerdcommenter'

" Tree
Plug 'preservim/nerdtree'

" Monokai colorscheme
Plug 'crusoexia/vim-monokai'

call plug#end()

colorscheme monokai

set number
" set relativenumber
set colorcolumn=101
set cursorline

let mapleader=" "
let maplocalleader=","
set shiftwidth=4 tabstop=4 expandtab
set scrolloff=3  " Keep the cursor N lines from the top or the bottom of the screen
set mouse=nv " Activate mouse support in normal and visual mode
set clipboard+=unnamed " Yanks/cut/deletes are put in the selection clipboard
" Quit with Q<CR>
nnoremap Q :qa

nnoremap <leader>d /<<<<<<< <cr>zz
nnoremap <leader>1 dd/=======<CR>V/>>>>>>> <CR>d/<<<<<<< <CR>zz
nnoremap <leader>2 ddV/=======<CR>d/>>>>>>> <CR>dd/<<<<<<< <CR>zz


" Ignore case unless use a capital in search (smartcase needs ignore set)
set ignorecase
set smartcase

""""""""""""""""
"  Utilities   "
""""""""""""""""

" Strip trailing whitespace with <leader>w
fun! <SID>StripTrailingWhitespaces()
    let l = line(".")
    let c = col(".")
    keepp %s/\s\+$//e
    call cursor(l, c)
endfun
nnoremap <leader>w :call <SID>StripTrailingWhitespaces()<CR>

" Reindent with <leader>=
nnoremap <leader>= gg=G
" Copy/Paste to clipboard
nnoremap <leader>p "+p
nnoremap <leader>y "+y
nnoremap <leader>s :set spell<CR>
nnoremap <leader>fr :set spell spelllang=fr<CR>

" Edit the vimrc easily

" Nerdtree
nnoremap <C-t> :NERDTreeToggle<CR>

" ── Secret hygiene ───────────────────────────────────────────────────────────
" Nvim persists buffer content to disk in ways that outlive the file itself:
" swapfiles (~/.local/state/nvim/swap), undofiles, and shada (which stores
" register contents — i.e. anything yanked). An OPENAI_API_KEY was once
" recovered from a swapfile months after the .envrc it came from was deleted.
" See prog/infra/secrets.md.

" Don't persist yanked text across sessions. `<0` = save no register lines,
" `s10` = skip items larger than 10KB. Marks and history still work.
set shada='100,<0,s10,h

" For files that hold secrets — including the temp file sops hands the editor,
" which keeps the original name (e.g. secrets.enc.yaml) under /tmp/sops*.
augroup secret_files
    autocmd!
    autocmd BufNewFile,BufReadPre *.enc.yaml,*.enc.yml,*.enc.json,*.enc.env,.env,.env.*,.envrc,*.age,/tmp/sops*/*
        \ setlocal noswapfile noundofile nobackup nowritebackup
augroup END
