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
