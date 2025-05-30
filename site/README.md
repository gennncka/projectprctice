# Автоматизация внутренних бизнес-процессов университета. 2ГИС

Веб-сайт проекта по автоматизации внутренних бизнес-процессов университета в сотрудничестве с 2ГИС.

## Описание

Проект представляет собой информационный веб-сайт, содержащий:
- Описание проекта и его целей
- Информацию о команде разработчиков
- Блог с новостями проекта
- Ресурсы и материалы

## Технологии
- HTML5
- CSS3
- JavaScript
- Адаптивный дизайн

## Журнал

### 1. Навигационное меню
```html
<nav>
    <ul class="menu">
        <li><a href="index.html">Главная</a></li>
        <li><a href="about.html">О проекте</a></li>
        <li><a href="team.html">Участники</a></li>
        <li><a href="blog.html">Журнал</a></li>
        <li><a href="resources.html">Ресурсы</a></li>
    </ul>
</nav>
```
### 2. Секция
```html
<section class="hero container">
    <h1>Автоматизация внутренних бизнес-процессов университета. 2ГИС</h1>
    <p>Инновационный проект по оптимизации передвижения...</p>
    <div class="hero-buttons">
        <a href="#features" class="btn btn-primary">Узнать больше</a>
        <a href="about.html" class="btn btn-secondary">О проекте</a>
    </div>
</section>
```
### 3. JS
- Анимация при скролле
```js
const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
        if (entry.isIntersecting) {
            entry.target.classList.add('visible');
        }
    });
});
```

- Плавная прокрутка
```js
window.scrollTo({
    top: offsetPosition,
    behavior: 'smooth'
});
```
## Развертывание
Сайт размещен на netlify и доступен по адресу: [[URL сайта] ](https://gennncka2gis.netlify.app)
